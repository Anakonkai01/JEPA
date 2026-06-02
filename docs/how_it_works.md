# How It Works — Architecture & Data Flow

## Sơ đồ tổng quan

```
┌─────────────────────────────────────┐         ┌──────────────────────────────────────────┐
│  RunCam WiFiLink 2 (drone side)     │         │  Laptop ground station                   │
│                                     │         │                                          │
│  ┌──────────┐  RTP  ┌────────────┐  │  WFB-NG │  ┌──────────┐  decrypted  ┌──────────┐  │
│  │ IMX415   ├──H265─►│  wfb_tx    │──┼─────────►│  wfb_rx   │──RTP UDP───►│ ffplay   │  │
│  │ sensor   │  RTP    │ (encrypt)  │  │ over   │  │ (decrypt) │  127.0.0.1: │ (decode  │  │
│  └──────────┘  local  │  /etc/     │  │ 5GHz   │  │ /home/.../ │  5600       │  + show) │  │
│                       │  drone.key │  │ ch161  │  │  gs.key    │             └──────────┘  │
│                       └────────────┘  │ MCS2   │  └──────────┘                            │
│                       wlan0 (RTL8812eu)│ 20MHz │  wlan1 (RTL8812AU monitor)              │
└─────────────────────────────────────┘         └──────────────────────────────────────────┘

                          Ethernet (chỉ debug, không bắt buộc):
                          camera 192.168.1.10  ←─RJ45─→  eth0 192.168.1.100 (USB-Eth)
```

## Các tầng dữ liệu (từ camera → mắt người)

1. **Sensor IMX415** → raw frames
2. **majestic** (camera process) encode frames → **H.265 NAL units**, push qua **RTP** sang local UDP socket (`rtp_local` = `127.0.0.1:<port>` trên camera)
3. **wfb_tx** đọc RTP packets từ `rtp_local`, encrypt bằng ChaCha20-Poly1305 với session key (derived qua curve25519 từ `/etc/drone.key`), gắn FEC (k=8, n=12 nghĩa là cứ 8 packet data thì có 4 packet redundant), inject vào không khí qua wlan0 ở channel 161, MCS index 2, 20 MHz bandwidth, BSSID `ff:ff:ff:ff:ff:ff`, SA/DA = `57:42:<link_id 3B>:<radio_port 1B>` (xem `wfb_ng_reference.md`)
4. **wlan1** (USB adapter trên laptop) ở **monitor mode**, channel 161, capture mọi 802.11 frame trên không khí
5. **wfb_rx** filter chỉ giữ frame có SA bắt đầu `57:42:75:05:d6:00` (link_id=7669206, radio_port=0), decrypt từng packet bằng `gs.key`, dùng FEC để recover packet mất, unwrap để lấy lại RTP payload, forward qua UDP unicast tới `127.0.0.1:5600`
6. **ffplay** mở SDP file để biết stream là RTP/H.265 PT97, listen UDP 5600, decode H.265 bằng libavcodec, render qua SDL (qua XWayland trên Wayland session)

## Vai trò các thành phần phần mềm

| Phần mềm | Vai trò | Bị thay thế bằng gì được? |
|---|---|---|
| **svpcom rtl8812au driver** | Monitor mode + raw frame injection cho RTL8812AU. Stock kernel module không làm được. | aircrack-ng/rtl8812au, morrownr/8812au-20210820 (chưa test) |
| **wfb-ng (wfb_rx)** | Decrypt + FEC + filter | Không có gì tương đương open source. fpv4win trên Windows là implementation khác cùng protocol. |
| **wfb-ng (wfb_keygen)** | Sinh curve25519 keypair | Chỉ cần chạy 1 lần khi setup |
| **ffplay (ffmpeg)** | Decode H.265 + render | gstreamer, vlc, mpv — đều OK |
| **sshpass** | Pipe password vào ssh (camera dùng password auth) | expect, hoặc setup SSH key |
| **ASIX driver mainline** | USB Ethernet adapter | Không thay, có sẵn trong kernel |

## Mạng và port nội bộ

| Port (laptop) | Protocol | Ai bind | Ai gửi | Nội dung |
|---|---|---|---|---|
| `5600/udp` | UDP unicast 127.0.0.1 | `ffplay` (qua SDP) | `wfb_rx` | RTP/H.265 video đã decrypt |
| `192.168.1.100:22` | TCP | (không) | — | — |
| (camera) `192.168.1.10:22` | TCP | dropbear | `ssh/sshpass` | Shell access |
| (camera) `192.168.1.10:554` | TCP | majestic RTSP | `ffplay` debug | RTSP fallback nếu WFB hỏng |

## Tại sao mọi thứ là vậy?

- **Monitor mode** cần thiết vì WFB-NG không dùng 802.11 association — nó broadcast raw frame với BSSID `ff:ff:ff:ff:ff:ff`. RX chỉ có thể bắt frame này khi NIC ở monitor mode (promiscuous + raw).
- **Channel 161 (5805 MHz) 20 MHz** vì camera được pre-cấu hình vậy. Phải khớp chính xác.
- **link_id = 7669206** là pre-assigned của camera, không đổi được dễ dàng. Chỉ cần đoán đúng bên ground.
- **Keypair phải sinh fresh** vì `/root/gs.key` trên camera không phải gs.key thật (xem `troubleshooting.md`).
- **SDP cho ffplay** vì RTP packet không tự khai báo codec; player cần meta từ ngoài.
- **Eth0 chỉ là helper** — sau khi setup key xong, có thể rút Ethernet và stream WFB vẫn chạy.
