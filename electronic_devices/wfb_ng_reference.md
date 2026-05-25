# WFB-NG Reference

Chi tiết kỹ thuật về WFB-NG (WiFi Broadcast Next Generation) — protocol, format
packet, cách filter. Đọc khi cần debug sâu hoặc viết tool tương tự.

## Tổng quan protocol

WFB-NG là **one-way broadcast** trên 802.11. Không có association, không có
ACK, không có retransmit ở tầng MAC. Tin cậy đến từ:

1. **FEC** (Forward Error Correction) ở tầng app — Reed-Solomon, mặc định `k=8, n=12`. Cứ 8 packet data gửi kèm 4 packet redundant, recover được tối đa 4 packet mất trong group.
2. **Crypto** — ChaCha20-Poly1305 AEAD. Session key ephemeral, exchange qua curve25519 dùng long-term keypair (`drone.key` ↔ `gs.key`).
3. **Channel diversity** — có thể chạy nhiều RX adapter, mỗi cái receive cùng frame, aggregator dedupe và chọn frame ngon nhất.

## Frame structure trên không khí

Mỗi packet WFB là một **802.11 data frame** với:

```
[Radiotap header (variable)] [802.11 MAC header (24B)] [LLC] [WFB payload]
```

### 802.11 MAC header — quan trọng nhất

| Field | Giá trị | Ý nghĩa |
|---|---|---|
| Frame Control | `0x0801` | Type=Data, Subtype=Data, ToDS=1 |
| Duration | 0 | — |
| **BSSID** (addr3) | `ff:ff:ff:ff:ff:ff` | Broadcast |
| **SA** (addr2) | `57:42:<channel_id 4B>` | Magic `WB` + channel_id |
| **DA** (addr1) | `57:42:<channel_id 4B>` | Giống SA |
| Seq | varies | — |

### channel_id encoding

```
channel_id = (link_id << 8) | radio_port
```

Trong đó:
- `link_id` là **24-bit** (3 bytes)
- `radio_port` là **8-bit** (1 byte)

Vậy channel_id chiếm **4 bytes** = byte 2-5 của MAC.

**Ví dụ thực tế của camera trong setup này:**
- MAC: `57:42:75:05:d6:00`
- byte 0-1: `57:42` (magic)
- byte 2-4: `75:05:d6` = link_id `0x7505d6` = **7669206 decimal**
- byte 5: `00` = radio_port 0

## BPF filter mà wfb_rx dùng

Trong `src/rx.cpp`:
```c
program = string_format("ether[0x0a:2]==0x5742 && ether[0x0c:4] == 0x%08x", channel_id);
```

Nghĩa là filter chỉ lấy frame có:
- Bytes 0x0a-0x0b (= MAC byte 0-1 sau radiotap, vị trí của addr2/SA) == `0x5742`
- Bytes 0x0c-0x0f (= addr2 byte 2-5) == channel_id 4 bytes

Tự dùng tcpdump trực tiếp:
```bash
sudo tcpdump -i wlan1 -nn -c 30 \
    'ether[0x0a:2]==0x5742 and ether[0x0c:4]==0x7505d600'
```

## CLI parameters `wfb_rx`

```
wfb_rx [-K rx_key] [-c client_addr] [-u client_port] [-p radio_port]
       [-R rcv_buf] [-l log_interval] [-e epoch] [-i link_id] interface1 [...]
```

| Flag | Default | Ý nghĩa |
|---|---|---|
| `-K` | `rx.key` | File gs.key (ground secret + drone public) |
| `-c` | `127.0.0.1` | IP để forward UDP đã decrypt |
| `-u` | `5600` | Port để forward UDP |
| `-p` | `0` | radio_port (filter — phải match TX) |
| `-i` | `0` | link_id **(decimal, không hex)** — phải match TX |
| `-e` | `0` | epoch (anti-replay) |
| `-R` | system default | UDP recv buffer size |
| `-l` | `1000` | Log PKT mỗi N ms |

**Bug cần biết:** `-i` parse bằng `atoi()` → chỉ hiểu decimal. `0x7505d6` sẽ thành `0`.

## CLI parameters `wfb_tx` (chạy trên camera, không trên ground)

```
wfb_tx -K drone_key [-M mcs] [-B bw] [-k fec_k] [-n fec_n] [-S stbc] [-L ldpc]
       [-G long_gi] [-i link_id] [-p radio_port] [-C ctrl_port] [-u udp_port]
       [-U udp_addr] interface
```

| Flag | Camera value | Ý nghĩa |
|---|---|---|
| `-M` | `2` | MCS index (rate tier) |
| `-B` | `20` | Bandwidth MHz (20/40/80) |
| `-k` | `8` | FEC data packets per group |
| `-n` | `12` | FEC total packets per group |
| `-U` | `rtp_local` | Đọc input từ UDP socket nội bộ |
| `-i` | `7669206` | link_id |
| `-C` | `8000` | control port (cho tx_cmd) |

## PKT log format từ `wfb_rx`

```
<timestamp_ms> PKT <p_all>:<b_all>:<p_dec_err>:<p_dec_ok>:<p_fec_rec>:<p_lost>:<p_bad>:<p_out>:<b_out>
```

| Field | Ý nghĩa | Healthy value |
|---|---|---|
| `p_all` | Total packets nhận được sau filter | > 0, tăng đều |
| `b_all` | Total bytes nhận | ~ 1MB/s ở 8Mbps |
| `p_dec_err` | Decrypt fail (key mismatch hoặc corruption) | ≈ 0 |
| `p_dec_ok` | Decrypt thành công | gần bằng p_all |
| `p_fec_rec` | Packet mất nhưng FEC recover được | nhỏ (vài %) |
| `p_lost` | Packet mất không recover được | < 5% |
| `p_bad` | Frame format sai | 0 |
| `p_out` | Packet forward ra UDP | gần bằng p_dec_ok |
| `b_out` | Bytes forward ra UDP | bằng bitrate camera |

## SESSION log

```
SESSION <epoch>:<n_sessions>:<fec_k>:<fec_n>
```

In ra khi nhận session packet (TX gửi định kỳ). Nếu thấy `SESSION` xuất hiện =
keypair đã match. Sau đó `p_dec_ok` mới có thể > 0.

Nếu **không bao giờ** thấy SESSION xuất hiện dù p_all > 0 → key mismatch. Frame
session encrypted bằng long-term key, fail luôn ở handshake.

## File format key (64 bytes)

`wfb_keygen` dùng libsodium curve25519. Mỗi file 64 bytes:

```
drone.key = drone_secret_key (32B) ++ gs_public_key (32B)
gs.key    = gs_secret_key    (32B) ++ drone_public_key (32B)
```

Hai file phải có MD5 **khác nhau**. Nếu giống → một file là copy của file kia, KHÔNG phải keypair.

## Tham khảo

- Source: https://github.com/svpcom/wfb-ng (branch `stable`)
- Header định nghĩa MAC: `src/wifibroadcast.hpp` line 144-162
- BPF filter: `src/rx.cpp` line 81
- Key file format: `src/keygen.c`
