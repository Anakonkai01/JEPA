# Hardware Inventory

## 1. Laptop (ground station host)

- **OS**: Arch Linux (omarchy distro), kernel `7.0.3-arch1-2`
- **User**: `anakonkai`, home `/home/anakonkai`
- **Built-in WiFi**: Intel iwlwifi (interface `wlan0`) — KHÔNG dùng cho WFB, dùng để vào mạng nhà bình thường
- **KHÔNG có port Ethernet** built-in — phải dùng USB-to-Ethernet adapter
- **Python**: miniconda installed (`/home/anakonkai/miniconda3/`) — KHÔNG dùng conda Python để build native code, luôn dùng `/usr/bin/python3`
- **Shell**: bash với zoxide (`cd` bị zoxide intercept → trong script tự động dùng `builtin cd` + absolute path)

## 2. USB WiFi adapter — RTL8812AU (RX wireless)

| Thông số | Giá trị |
|---|---|
| USB ID | `0bda:8812` |
| Model | Realtek RTL8812AU 802.11a/b/g/n/ac 2T2R |
| Form factor | AC-1200, 2 antennas ngoài |
| USB version | 2.0 High Speed (480 Mbps) — chip không support USB 3 |
| Interface trên Linux | `wlan1` (có thể đổi thành `wlan2` khi replug, luôn check `ip link`) |
| MAC | `00:13:ef:20:01:70` |
| Driver | `rtl88xxau_wfb` (module name `88XXau_wfb`) — svpcom v5.2.20.2_28373.20190919, build via DKMS |
| Source | `/home/anakonkai/rtl8812au/` |
| Module path | `/lib/modules/7.0.3-arch1-2/updates/dkms/88XXau_wfb.ko.zst` |

**Lưu ý driver:** Driver svpcom viết cho kernel ~5.15 nhưng vẫn build & chạy được trên 7.0.3.
Driver khác đã thử nhưng fail trên kernel này: `lwfinger/rtl8812au`, AUR `rtl8812au-dkms-git`.
Stock kernel module `rtw88_88xxa` không bind được adapter trong monitor mode (không
support inject) — đó là lý do phải dùng svpcom fork.

## 3. USB-to-Ethernet adapter — ASIX AX88179

| Thông số | Giá trị |
|---|---|
| USB ID | `0b95:1790` |
| Model | ASIX AX88179 Gigabit Ethernet |
| Interface trên Linux | `eth0` (driver mainline `ax88179_178a`, không cần cài) |
| MAC | `6c:1f:f7:62:e4:3b` |
| IP đang dùng | `192.168.1.100/24` (static, để cùng subnet với camera 192.168.1.10) |

Chỉ dùng để SSH/SCP vào camera. KHÔNG cần thiết khi chỉ nhận stream WFB.

## 4. Camera — RunCam WiFiLink 2

| Thông số | Giá trị |
|---|---|
| Firmware | RunCam OpenIPC |
| SoC | (OpenIPC family) |
| Sensor | Sony IMX415 |
| Video | 1280×720 @ 120fps, H.265, 8192 kbps CBR, GOP=1 |
| Codec config | `/etc/majestic.yaml` |
| Power | 7-26V DC (test ở 20V OK) |
| Ethernet IP | `192.168.1.10` (static) |
| SSH | `root@192.168.1.10`, password `12345`, dropbear server |
| SCP quirk | Phải dùng `scp -O` (legacy mode, không có sftp-server) |
| RTSP fallback | `rtsp://root:12345@192.168.1.10:554/stream=0` (qua Ethernet, dùng `ffplay -rtsp_transport tcp ...`) |

### Processes WFB trên camera (sau khi `S98wifibroadcast start`)

```
wfb_tx -K /etc/drone.key -M 2 -B 20 -k 8 -n 12 -U rtp_local -S 0 -L 0 -i 7669206 -C 8000 wlan0   # video TX
wfb_rx -K /etc/drone.key -i 7669206 -p 160 -u 5800 wlan0                                          # uplink RX
wfb_tx -K /etc/drone.key -M 1 -B 20 -k 8 -n 12 -S 0 -L 0 -i 7669206 -p 32 -u 5801 wlan0          # telemetry TX
wfb_tun -a 10.5.0.10/24                                                                            # IP tunnel
wfb_rx -K /etc/drone.key -i 7669206 -p 144 -u 14550 wlan0                                         # mavlink RX
wfb_tx -K /etc/drone.key -M 1 -B 20 -k 8 -n 12 -S 0 -L 0 -i 7669206 -p 16 -u 14551 wlan0         # mavlink TX
```

Video stream là process đầu (`-p 0` mặc định, `-U rtp_local`).
