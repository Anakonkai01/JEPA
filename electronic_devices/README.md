# electronic_devices — RunCam WiFiLink 2 Ground Station

Tài liệu cho ground station nhận video từ **RunCam WiFiLink 2** qua WFB-NG,
chạy trên **Arch Linux (omarchy)** kernel 7.0.3, dùng USB WiFi adapter
RTL8812AU. Mục tiêu cuối là feed video vào OpenCV cho dự án xe RC tự lái
(behavioral cloning).

## Trạng thái: ✅ WORKING (2026-05-25)

Stream RTP/H.265 nhận được, decrypt được, decode được, hiển thị trong ffplay.
Bước tiếp theo là tích hợp OpenCV (xem `next_steps.md`).

## Cấu trúc tài liệu

| File | Mục đích | Đọc khi nào |
|---|---|---|
| [`README.md`](README.md) | Bạn đang đọc. Entry point + quick start | Bắt đầu |
| [`hardware.md`](hardware.md) | Danh sách thiết bị, USB IDs, MAC, specs | Cần check phần cứng |
| [`how_it_works.md`](how_it_works.md) | Kiến trúc, data flow, vai trò mỗi thành phần | Muốn hiểu hệ thống |
| [`setup_from_scratch.md`](setup_from_scratch.md) | Cài đặt từ đầu (sau khi reset máy) | Build lại từ con số 0 |
| [`daily_use.md`](daily_use.md) | Lệnh chạy hàng ngày (sau reboot/replug) | Dùng ngay, đã setup xong |
| [`troubleshooting.md`](troubleshooting.md) | Lỗi thường gặp + cách fix | Khi không chạy |
| [`wfb_ng_reference.md`](wfb_ng_reference.md) | Chi tiết kỹ thuật WFB-NG protocol | Debug sâu |
| [`next_steps.md`](next_steps.md) | OpenCV integration roadmap | Sau khi hoàn tất ground station |

## Quick start (nếu đã setup rồi)

Mở 2 terminal:

**Terminal 1** — set up wlan1 + nhận stream:
```bash
sudo ip link set wlan1 down
sudo iw wlan1 set monitor otherbss
sudo ip link set wlan1 up
sudo iw wlan1 set channel 161 HT20
sudo /home/anakonkai/wfb-ng/wfb_rx -p 0 -u 5600 -K /home/anakonkai/gs.key -i 7669206 wlan1
```

**Terminal 2** — xem video:
```bash
ffplay -protocol_whitelist file,rtp,udp \
       -fflags nobuffer -flags low_delay -framedrop \
       -i /home/anakonkai/runcam.sdp
```

Nếu lỗi → xem [`troubleshooting.md`](troubleshooting.md).

## File quan trọng ngoài thư mục này

| File | Chức năng |
|---|---|
| `/home/anakonkai/gs.key` | Ground station decryption key (64 bytes, matched pair với `/etc/drone.key` trên camera) |
| `/home/anakonkai/drone.key` | Bản drone của keypair — backup, không dùng ở ground side |
| `/home/anakonkai/gs.key.original.*` | Backup key cũ (sai) trước khi gen mới — đừng dùng |
| `/home/anakonkai/runcam.sdp` | RTP/H.265 SDP descriptor cho ffplay |
| `/home/anakonkai/wfb-ng/` | Source + binaries wfb-ng (đã build) |
| `/home/anakonkai/rtl8812au/` | Source driver svpcom (đã build qua DKMS) |
| `/etc/modprobe.d/blacklist-rtw88.conf` | Blacklist (sai tên module, chưa fix nhưng không block) |

Trên camera (qua SSH `root@192.168.1.10` pw `12345`):

| File | Chức năng |
|---|---|
| `/etc/drone.key` | Encryption key đang dùng (đã thay bằng key keypair mới) |
| `/etc/drone.key.orig.bak` | Backup key gốc của RunCam (đề phòng cần khôi phục) |
| `/etc/majestic.yaml` | Cấu hình camera (resolution, codec, bitrate, fps) |
| `/etc/init.d/S98wifibroadcast` | Init script của WFB (chỉ có `start`/`stop`, không có `restart`) |
