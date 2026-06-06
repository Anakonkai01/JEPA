# Troubleshooting

Tất cả các lỗi đã gặp trong setup này + cách fix. Đọc theo triệu chứng.

## A. wfb_rx in `PKT 0:0:0:0:0:0:0:0:0` mãi (0 packets received)

Nghĩa là wfb_rx đang chạy nhưng không có packet nào lọt qua BPF filter của nó.

### Check 1: wlan1 có ở monitor mode + channel 161 không?

```bash
iw wlan1 info
```

Phải show `type monitor`, `channel 161 (5805 MHz), width: 20 MHz`. Nếu thấy
`type managed` hoặc `channel 1` → chưa set xong. Chạy lại sequence
`down → set monitor → up → set channel` ở `daily_use.md` mục 1.

⚠️ USB replug HOẶC service NetworkManager (nếu có) sẽ reset interface về managed/ch1.

### Check 2: Có frame WFB-NG nào trên không không?

```bash
sudo tcpdump -i wlan1 -nn -e -c 30 -s 200 2>&1 | head -40
```

- Nếu **không có dòng nào** chứa `5805 MHz` → wlan1 không capture được gì. Kiểm tra driver: `ethtool -i wlan1` phải show `driver: rtl88xxau_wfb`. Nếu driver khác → blacklist conflict.
- Nếu có frame nhưng **không có** `SA:57:42:xx:xx:xx:xx` → camera không phát hoặc phát ở channel/link_id khác. Check camera đang power lên, đèn LED, distance gần (<3m).
- Nếu có frame `SA:57:42:75:05:d6:00` → camera OK, vấn đề ở `-i` parameter (xem check 3).

### Check 3: link_id đúng chưa?

`wfb_rx -i` dùng `atoi()` → **chỉ decimal**, không hex. Camera của setup này dùng
`link_id = 7669206` (= 0x7505d6). MAC source thật trên frame là
`57:42 : <link_id 3 bytes BE> : <radio_port 1 byte>`. Nếu thấy MAC khác trong
tcpdump, đổi `-i` cho phù hợp:

```python
# Tính ngược: từ MAC 57:42:AA:BB:CC:DD
link_id = (0xAA << 16) | (0xBB << 8) | 0xCC
radio_port = 0xDD
```

## B. wfb_rx in `Unable to decrypt packet #...` liên tục

Frame lọt qua filter (số counter trong PKT tăng) nhưng decrypt fail. Nghĩa là
**`gs.key` không match `/etc/drone.key` trên camera**.

### Cái bẫy: `/root/gs.key` trên camera là LIE

Camera có sẵn file `/root/gs.key` 64 bytes. Người ta tưởng đó là gs.key cần
copy. **Sai** — file này có **cùng MD5** với `/etc/drone.key`, tức là chỉ là copy
của drone.key chứ không phải nửa kia của keypair.

```bash
sshpass -p '12345' ssh root@192.168.1.10 'md5sum /root/gs.key /etc/drone.key'
# Cả 2 dòng có cùng hash → CHỨNG MINH bẫy
```

### Fix: gen keypair fresh và push drone.key mới

```bash
cd /home/anakonkai
~/wfb-ng/wfb_keygen   # ghi đè ~/gs.key và ~/drone.key
md5sum gs.key drone.key   # phải KHÁC nhau

sshpass -p '12345' ssh root@192.168.1.10 'cp /etc/drone.key /etc/drone.key.bak.$(date +%s)'
sshpass -p '12345' scp -O drone.key root@192.168.1.10:/etc/drone.key
sshpass -p '12345' ssh root@192.168.1.10 \
    '/etc/init.d/S98wifibroadcast stop && sleep 2 && /etc/init.d/S98wifibroadcast start'
```

Sau đó wfb_rx phải in `SESSION 0:1:8:12` và `count_p_dec_ok` > 0.

### Nếu vẫn không decrypt sau khi push key mới

- Kiểm tra `ps` trên camera xem wfb_tx có thực sự load key mới không (so md5 file đang dùng).
- Có thể `S98wifibroadcast` cache key — thử reboot camera: `reboot` qua SSH.

## C. SCP fail: `subsystem request failed on channel 0` hoặc `Connection closed`

Camera firmware OpenIPC không có `sftp-server`. Phải dùng SCP legacy:

```bash
scp -O ...      # bắt buộc -O
```

## D. SSH refused dù ping OK

- Camera vừa boot lên, dropbear chưa start. Đợi thêm 10-15s.
- Hoặc route đang sai — `ip route get 192.168.1.10` phải show `dev eth0`. Nếu show `dev wlan0` → bạn đang ping nhầm thiết bị khác trên cùng dải IP qua WiFi (ví dụ router/switch). Set `eth0` IP rồi route mới đúng.

## E. ffplay window đen / không hiện

- Thử log: tail file `/tmp/ffplay.log` xem có lỗi codec không.
- Kiểm tra `wfb_rx` thực sự đang forward UDP: `sudo timeout 2 nc -u -l 5600` từ terminal khác — nếu KHÔNG nhận byte nào → wfb_rx chưa decrypt được.
- Nếu UDP có data nhưng ffplay đen → có thể SDP sai. Verify file `/home/anakonkai/runcam.sdp` có đúng `m=video 5600 RTP/AVP 97` và `a=rtpmap:97 H265/90000`.
- Wayland session: ffplay tự dùng XWayland, không cần extra config. Verify `DISPLAY=:0`.

## F. `make all_bin` của wfb-ng fail với `ValueError: invalid literal for int() with base 10: 'unknown'`

Shallow clone không có git history nên `version.py` không lấy được timestamp. Patch
file (xem `setup_from_scratch.md` mục 4a) — bọc `try/except` và default branch.

## G. `ModuleNotFoundError: No module named 'setuptools'` khi build wfb-ng

Arch Python 3.14 không có setuptools mặc định, và pip bị PEP 668 chặn. Cài qua
pacman:

```bash
sudo pacman -S python-setuptools python-pyroute2 python-msgpack
```

⚠️ **Đừng** dùng `conda install` hay `pip install --user` — miniconda có sẵn trên
máy này nhưng wfb-ng build script cần system Python.

## H. lsmod show `rtw88_88xxa` đang load — có sao không?

Không sao nếu refcount = 0 (cột thứ 3 của lsmod). Module nằm im trong memory
nhưng không bind adapter. Driver thực bind wlan1 là `rtl88xxau_wfb` (svpcom),
verify qua `ethtool -i wlan1`.

Để dọn sạch:
```bash
sudo rmmod rtw88_88xxa rtw88_core 2>/dev/null
# Và sửa blacklist (file hiện đang sai tên):
echo 'blacklist rtw88_88xxa' | sudo tee -a /etc/modprobe.d/blacklist-rtw88.conf
```

## I. wlan1 biến mất sau khi set channel

Sequence sai. Phải làm đúng thứ tự: `link down → set monitor → link up → set channel`.
Nếu set channel TRƯỚC khi up, hoặc up TRƯỚC khi set monitor, có thể driver reset
interface. Sau khi mất, replug USB hoặc:

```bash
sudo ip link set wlan1 down && sudo ip link set wlan1 up
```

## J. Interface tên đổi từ wlan1 sang wlan2 sau replug

Đây là behavior bình thường của udev khi cùng adapter cắm vào port USB khác.
Luôn check `ip link` trước khi chạy lệnh. Có thể bind tên cố định bằng udev rule
theo MAC:

```
# /etc/udev/rules.d/70-persistent-net.rules
SUBSYSTEM=="net", ACTION=="add", ATTR{address}=="00:13:ef:20:01:70", NAME="wfbrx0"
```
