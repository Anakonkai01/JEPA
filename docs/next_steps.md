# Next Steps — OpenCV Integration

Ground station đã chạy. Đích cuối là **xe RC tự lái dùng behavioral cloning**,
input là camera stream qua OpenCV.

## Mục tiêu

```python
import cv2
cap = cv2.VideoCapture("udp://127.0.0.1:5600")
while True:
    ok, frame = cap.read()
    if not ok: continue
    # → frame là numpy array BGR, đưa vào model PyTorch/TF
```

## Vấn đề kỹ thuật cần giải quyết

OpenCV backend (FFMPEG) cần biết stream là RTP/H.265, không phải raw UDP. Một
số cách:

### Cách 1: SDP file qua ffmpeg backend env

```python
import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "protocol_whitelist;file,rtp,udp"
cap = cv2.VideoCapture("/home/anakonkai/runcam.sdp", cv2.CAP_FFMPEG)
```

⚠️ Chưa test trong setup này. OpenCV version trong miniconda có thể build không
kèm RTP support → cần check `cv2.getBuildInformation()`.

### Cách 2: ffmpeg subprocess + pipe BGR raw

Bypass OpenCV's VideoCapture, dùng subprocess:

```python
import subprocess, numpy as np

W, H = 1280, 720
proc = subprocess.Popen([
    "ffmpeg", "-protocol_whitelist", "file,rtp,udp",
    "-fflags", "nobuffer", "-flags", "low_delay",
    "-i", "/home/anakonkai/runcam.sdp",
    "-pix_fmt", "bgr24",
    "-f", "rawvideo",
    "-"
], stdout=subprocess.PIPE, bufsize=10**8)

frame_size = W * H * 3
while True:
    raw = proc.stdout.read(frame_size)
    if len(raw) != frame_size:
        break
    frame = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3))
    # ... model.predict(frame) ...
```

✅ **Cách này luôn work** (không phụ thuộc OpenCV build). Latency tốt, dùng CPU
decode hoặc add `-hwaccel vaapi` cho GPU decode.

### Cách 3: GStreamer pipeline qua OpenCV

```python
pipeline = (
    "udpsrc port=5600 caps=\"application/x-rtp,media=video,clock-rate=90000,"
    "encoding-name=H265,payload=97\" ! "
    "rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! appsink"
)
cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
```

Cần OpenCV build kèm GStreamer (`gstreamer1.0-libav` + `gstreamer1.0-plugins-good`).
Latency thường tốt nhất.

## Đề xuất ưu tiên

1. **Test Cách 2 trước** (ffmpeg subprocess) — đơn giản, đảm bảo work
2. Nếu cần latency thấp hơn → Cách 3 (GStreamer)
3. Cách 1 chỉ dùng nếu environment đã có OpenCV+FFMPEG đầy đủ

## Lo lắng performance

- **Bitrate camera**: 8 Mbps H.265 1280×720 @ 120fps
- **Decode CPU**: H.265 software decode tốn ~15-25% 1 core trên CPU modern. 120fps có thể bottleneck → giảm fps trong `/etc/majestic.yaml` xuống 60fps nếu không cần
- **Latency end-to-end** (camera → numpy): ước tính ~80-150ms (WFB queue + decode buffer + frame interval)
- **Behavioral cloning** thường chạy inference 10-30 FPS → drop frame qua `cap.read()` non-blocking là OK

## Recording cho training data

Đồng thời ghi stream ra file trong khi xem:

```bash
# Tee UDP stream sang 2 đích
# Hoặc đơn giản dùng ffmpeg để vừa record vừa display
ffmpeg -protocol_whitelist file,rtp,udp -i /home/anakonkai/runcam.sdp \
       -c copy training_$(date +%s).mp4 \
       -c:v rawvideo -pix_fmt bgr24 -f sdl "preview"
```

Hoặc dùng Python script: record `(frame, steering_angle, throttle)` triplets vào
HDF5/Parquet, mỗi frame là numpy array.

## Kiến trúc gợi ý cho self-driving pipeline

```
camera (drone)
   │ WFB-NG
   ▼
ground station (đã xong)
   │ UDP 5600 RTP/H.265
   ▼
ffmpeg subprocess (decode)
   │ stdout pipe BGR raw
   ▼
Python loop
   ├─► model.predict() ──► steering + throttle ──► serial/Bluetooth ──► xe RC
   └─► record to disk (training)
```

## Sub-task TODO khi bắt tay làm

- [ ] Test `cv2.VideoCapture` với SDP path
- [ ] Nếu không work → viết ffmpeg subprocess wrapper class
- [ ] Đo latency thực tế (frame capture timestamp vs render)
- [ ] Tích hợp với model inference
- [ ] Test reconnect logic (camera mất tín hiệu → wfb_rx restart → có tự nối lại không)
- [ ] (Optional) Service systemd để auto-start wfb_rx khi boot
