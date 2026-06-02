# Setup From Scratch

Đây là toàn bộ các bước nếu phải dựng lại từ một máy Arch mới tinh. Đã verified
ngày 2026-05-25 trên kernel 7.0.3.

## 0. Prerequisites

- Arch Linux đã cài, có `sudo` access
- USB WiFi adapter RTL8812AU (`0bda:8812`) đã cắm
- USB-to-Ethernet adapter (bất kỳ loại nào mainline kernel nhận — ASIX AX88179 đã test)
- Camera RunCam WiFiLink 2 đã có firmware OpenIPC + đang phát WFB ở ch 161
- Cáp Ethernet để nối camera ↔ USB-Eth adapter
- Cáp/bộ nguồn 7-26V cho camera

## 1. Cài packages từ pacman

```bash
sudo pacman -S --needed \
    base-devel git linux-headers dkms \
    python python-setuptools python-pyroute2 python-msgpack \
    libsodium libpcap libnl \
    ffmpeg iw aircrack-ng tcpdump \
    sshpass
```

## 2. Blacklist driver kernel stock (cẩn thận)

⚠️ Tên module thực tế là `rtw88_88xxa` (không phải `rtw88_8812au`). File hiện có sai tên
nhưng không gây vấn đề vì module không bind adapter. Để chính xác:

```bash
sudo tee /etc/modprobe.d/blacklist-rtw88.conf <<EOF
blacklist rtw88_88xxa
blacklist rtw88_8812au
blacklist rtw88usb
EOF
```

## 3. Build & install svpcom rtl8812au driver (qua DKMS)

```bash
cd ~
git clone https://github.com/svpcom/rtl8812au.git
cd rtl8812au
sudo make dkms_install   # hoặc tự make + cp module
```

Sau cài đặt:
```bash
sudo modprobe 88XXau_wfb
ip link    # kiểm tra có wlan1 không
ethtool -i wlan1   # phải show driver: rtl88xxau_wfb
```

Nếu kernel update sau này, DKMS sẽ tự rebuild module mới.

## 4. Build wfb-ng

```bash
cd ~
git clone --branch stable https://github.com/svpcom/wfb-ng.git
cd wfb-ng
```

### 4a. Patch `version.py` (bug với shallow clone)

Sửa file `version.py` — bọc `int(sys.argv[1])` trong try/except và default branch:

```python
def main():
    try:
        ttuple = time.gmtime(int(sys.argv[1]))
    except (ValueError, IndexError):
        ttuple = time.gmtime(0)
    branch = sys.argv[2] if len(sys.argv) > 2 else 'stable'
```

### 4b. Build

```bash
make all_bin
```

Sau đó kiểm tra:
```bash
ls -la wfb_rx wfb_tx wfb_keygen wfb_tx_cmd wfb_tun   # phải có cả 5
./wfb_rx 2>&1 | head -3   # phải in usage
```

## 5. Setup USB Ethernet để SSH vào camera

Cắm USB-Eth adapter + cáp từ camera RJ45 → adapter.

```bash
sudo ip addr flush dev eth0
sudo ip addr add 192.168.1.100/24 dev eth0
sudo ip link set eth0 up
ping -c 2 192.168.1.10   # camera phải reply ~1-3ms
```

## 6. Sinh keypair mới + push lên camera

⚠️ Đây là bước **bắt buộc**. KHÔNG dùng file `/root/gs.key` có sẵn trên camera —
nó chỉ là copy của drone.key, không phải pair hợp lệ. Xem `troubleshooting.md` chi tiết.

```bash
cd ~
~/wfb-ng/wfb_keygen   # sinh gs.key + drone.key trong cwd
md5sum gs.key drone.key   # 2 file phải KHÁC md5 — nếu giống là wfb_keygen bug
```

Backup key cũ trên camera + push key mới:

```bash
sshpass -p '12345' ssh -o StrictHostKeyChecking=no root@192.168.1.10 \
    'cp /etc/drone.key /etc/drone.key.orig.bak'
sshpass -p '12345' scp -O ~/drone.key root@192.168.1.10:/etc/drone.key

# Restart WFB trên camera (không có 'restart' action — phải stop rồi start)
sshpass -p '12345' ssh -o StrictHostKeyChecking=no root@192.168.1.10 \
    '/etc/init.d/S98wifibroadcast stop && sleep 2 && /etc/init.d/S98wifibroadcast start'
```

## 7. Tạo SDP file cho ffplay

```bash
cat > ~/runcam.sdp <<'EOF'
v=0
o=- 0 0 IN IP4 127.0.0.1
s=RunCam WiFiLink 2
c=IN IP4 127.0.0.1
t=0 0
m=video 5600 RTP/AVP 97
a=rtpmap:97 H265/90000
EOF
```

## 8. Test toàn chuỗi

```bash
# Set wlan1 monitor + channel
sudo ip link set wlan1 down
sudo iw wlan1 set monitor otherbss
sudo ip link set wlan1 up
sudo iw wlan1 set channel 161 HT20
iw wlan1 info | grep -E "type|channel"   # phải có type monitor, channel 161

# Chạy wfb_rx
sudo ~/wfb-ng/wfb_rx -p 0 -u 5600 -K ~/gs.key -i 7669206 wlan1
# → quan sát log:
#   - SESSION 0:1:8:12  (session handshake OK)
#   - PKT 1000:1.4M:0:1000:...  (count_dec_ok > 0, count_dec_err nhỏ/0)
```

Mở terminal khác:
```bash
ffplay -protocol_whitelist file,rtp,udp \
       -fflags nobuffer -flags low_delay -framedrop \
       -i ~/runcam.sdp
```

Nên thấy video. Nếu không → `troubleshooting.md`.

## 9. (Optional) Persistent setup khi reboot

Hiện tại các config trên (monitor mode, eth0 IP) sẽ mất sau reboot vì chỉ
runtime. Để persistent có thể tạo systemd service hoặc udev rule. **Chưa làm**
vì user muốn manual control trong giai đoạn dev.

Tham khảo udev rule mẫu:
```
# /etc/udev/rules.d/99-wlan-monitor.rules
ACTION=="add", SUBSYSTEM=="net", DRIVERS=="rtl88xxau_wfb", \
    RUN+="/usr/bin/iw %k set monitor otherbss", \
    RUN+="/usr/bin/iw %k set channel 161 HT20"
```
