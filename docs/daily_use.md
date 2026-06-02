# Daily Use — Cheat Sheet

Dùng khi đã setup xong (`setup_from_scratch.md` hoàn tất), chỉ cần chạy stream
hàng ngày.

## Trước khi bắt đầu

- Cắm USB WiFi adapter (RTL8812AU) — check tên: `ip link | grep wlan` (có thể là `wlan1` hoặc `wlan2`)
- Cấp nguồn camera (7-26V)
- (Optional, chỉ cho debug) Cắm USB-Eth adapter + cáp tới camera

## Khởi động ground station (3 lệnh)

Giả định interface là `wlan1`. Nếu USB replug đổi sang `wlan2`, sửa cho phù hợp.

### 1. Set wlan1 sang monitor mode + channel 161

```bash
sudo ip link set wlan1 down && \
sudo iw wlan1 set monitor otherbss && \
sudo ip link set wlan1 up && \
sudo iw wlan1 set channel 161 HT20
```

Verify:
```bash
iw wlan1 info
# Phải show:  type monitor   channel 161 (5805 MHz), width: 20 MHz
```

### 2. Chạy wfb_rx

```bash
sudo /home/anakonkai/wfb-ng/wfb_rx \
    -p 0 -u 5600 -K /home/anakonkai/gs.key -i 7669206 wlan1
```

**Log lành mạnh trông như:**
```
... SESSION 0:1:8:12          ← session handshake OK
... PKT 1039:1422799:35:1004:87:3:0:753:986059
        │       │       │   │    │  │ │  │     └─ bytes out (≈ 1 MB/s ở 8 Mbps bitrate)
        │       │       │   │    │  │ │  └─ packets out (≈ 750/s)
        │       │       │   │    │  │ └─ bad packets
        │       │       │   │    │  └─ lost (chấp nhận được nếu < 5%)
        │       │       │   │    └─ FEC recovered
        │       │       │   └─ decrypt OK
        │       │       └─ decrypt error (≈ 0 nếu key match)
        │       └─ bytes in
        └─ packets in
```

Nếu thấy `Unable to decrypt packet #...` liên tục → key mismatch → xem `troubleshooting.md`.

### 3. Xem video (terminal khác)

```bash
ffplay -protocol_whitelist file,rtp,udp \
       -fflags nobuffer -flags low_delay -framedrop \
       -i /home/anakonkai/runcam.sdp
```

Vài giây đầu có thể thấy lỗi `Error constructing the frame RPS` — bình thường,
ffplay đang đợi keyframe đầu tiên. Sau ~1-3s video sẽ hiện.

## Dừng

```bash
sudo pkill wfb_rx
pkill ffplay
```

## Lệnh debug hay dùng

### Xem có frame WFB nào không (kể cả khi wfb_rx fail)

```bash
sudo tcpdump -i wlan1 -nn -e -c 20 -s 200 \
    'ether[0x0a:2]==0x5742 and ether[0x0c:3]==0x7505d6'
```
Filter này lọc đúng frame của camera (magic `WB` + link_id 0x7505d6).

### Camera còn sống không (qua Ethernet)

```bash
ping -c 2 192.168.1.10
sshpass -p '12345' ssh root@192.168.1.10 'ps | grep wfb_tx | grep -v grep'
```

### Restart WFB trên camera (khi đổi key hoặc cấu hình)

```bash
sshpass -p '12345' ssh root@192.168.1.10 \
    '/etc/init.d/S98wifibroadcast stop && sleep 2 && /etc/init.d/S98wifibroadcast start'
```

### Lưu stream ra file MP4

Chạy thay cho ffplay (vẫn cần wfb_rx chạy):
```bash
ffmpeg -protocol_whitelist file,rtp,udp -i /home/anakonkai/runcam.sdp \
       -c copy -f mp4 -y output.mp4
# Ctrl-C để stop
```

### Latency thấp hơn với `-flags2 fast` và tăng `-probesize`

```bash
ffplay -protocol_whitelist file,rtp,udp \
       -fflags nobuffer -flags low_delay -flags2 fast \
       -probesize 32 -analyzeduration 0 \
       -framedrop -i /home/anakonkai/runcam.sdp
```
