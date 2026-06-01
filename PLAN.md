# RC Car Self-Driving — V-JEPA 2.1 Project Plan

## Overview

**Đề tài:** Action-Conditioned World Model for RC Car Navigation based on V-JEPA 2.1
**Novel contribution:** First evaluation của V-JEPA 2 family trên mobile robot (RC car) — Meta chỉ test trên robot arm
**Deadline: 2026-06-15** (~19 ngày từ 2026-05-27)

---

## System Architecture

```
[RunCam WiFiLink 2]
  --WFB-NG (RTL8812AU, wlan1, ch161, H.265)--> [PC: RTX 5070 Ti]
  ffmpeg pipe -> BGR frames (1280x720)
  V-JEPA 2.1 encoder (FROZEN, ViT-L) -> latent s_t (1024-dim)
  AC Predictor(s_t, a_t) -> ŝ_{t+1}
  CEM planning -> best action sequence
  [PC] --UDP 2 bytes--> [ESP32-S3 @ 192.168.1.23:4210]
    -> GPIO 5: Servo N680 HV (steering, 50Hz PWM, 1142–1880µs)
    -> GPIO 6: ESC QuicRun 8BL150 (throttle, 50Hz PWM, 1000–2000µs)
```

---

## Hardware

| Component | Specs |
|-----------|-------|
| Camera | RunCam WiFiLink 2, IMX415, 1280×720@120fps, H.265 8Mbps |
| RX Radio | RTL8812AU (wlan1), monitor mode, ch161 HT20 |
| WFB link | link_id=7669206, radio_port=0, key=~/gs.key |
| Compute | RTX 5070 Ti, Arch Linux kernel 7.0.3 |
| Controller | ESP32-S3 WROOM 16MB/8MB @ 192.168.1.23 |
| Steering servo | KDS N680 HV Metal Gear Digital, 6.0V–8.4V, 16–19kg.cm |
| ESC | Hobbywing QuicRun WP 8BL150 (150A brushless waterproof) |
| Power | 20V drill battery → ESC main; BEC 6V/3A → Servo |
| ESP32 power | Separate 5V (USB hoặc step-down từ BEC) |

### Wiring Diagram

```
[20V drill battery] ──thick──> [QuicRun 8BL150 ESC]
                                     │
                              BEC out (3-pin connector):
                              red  (+6V) ──────────────> Servo V+
                              black (GND) ─────────────> Servo GND
                                                         ESP32 GND
                              orange (Signal) <───────── ESP32 GPIO 6
                                     │
                              [Motor leads x3] ──> Brushless motor

[ESP32-S3] ─GPIO 5────────────────────────────────> Servo Signal
           ─GPIO 6────────────────────────────────> ESC Signal (orange above)
           ─GND──────────────────────────────────── Common GND
           ─5V (USB/separate) ────────────────────> ESP32 VIN

```

**Lưu ý quan trọng:**
- N680 HV cần 6V–8.4V để hoạt động, đúng với BEC 6V của ESC
- ESC cần nhận neutral (1500µs) trong ~2 giây sau khi bật nguồn mới arm — firmware phải output neutral ngay khi boot
- ESP32 GPIO output 3.3V logic: đủ để kích servo và ESC (threshold thường ≥ 2.0V)
- Tuyệt đối không nối 6V BEC vào ESP32 3.3V pin — chỉ nối GND chung

### PWM Spec (từ thực nghiệm calibrate)

| Signal | Frequency | Min | Neutral | Max |
|--------|-----------|-----|---------|-----|
| Servo N680 HV | 50Hz | 1142µs (full left) | 1500µs | 1880µs (full right) |
| ESC QuicRun 8BL150 | 50Hz | 1000µs (full reverse) | 1500µs | 2000µs (full forward) |

Servo limits từ 5 lần thực nghiệm, trung bình ± 10µs safety padding — xem `rc-carcar/specs.md`.

Mapping từ byte (0–255) cho steering: `pulse_us = 1142 + (byte / 255.0) * (1880 - 1142)`
Mapping từ byte (0–255) cho throttle: `pulse_us = 1000 + (byte / 255.0) * 1000`
- byte=0 → min, byte=127 → ~neutral, byte=255 → max

---

## Training Pipeline

```
frame_t   -> V-JEPA encoder (frozen) -> s_t   ─┐
action_t  ─────────────────────────────────────→ AC Predictor -> ŝ_{t+1}
frame_{t+1} -> V-JEPA encoder (frozen) -> s_{t+1} (ground truth)
Loss: MSE(ŝ_{t+1}, s_{t+1}) + 0.5 * (1 - cosine_sim(ŝ_{t+1}, s_{t+1}))
```

**Key optimization:** Pre-encode toàn bộ dataset offline (1 lần) → lưu latent tensors `data/latents/*.pt` → training load trực tiếp, không forward qua V-JEPA → nhanh 50–100x.

---

## Project Structure

```
JEPA/
├── PLAN.md                    ← file này
├── CLAUDE.md
├── requirements.txt
├── .gitignore
├── test.py                    ← PoC capture (keep)
│
├── src/
│   ├── capture.py             ← Phase 1: ffmpeg pipe → BGR frames
│   ├── encoder.py             ← Phase 1: V-JEPA 2.1 frozen encoder wrapper
│   ├── controller.py          ← Phase 1: UDP sender → ESP32
│   ├── recorder.py            ← Phase 2: sync video + action logging
│   ├── offline_encode.py      ← Phase 2: batch encode → latent .pt
│   ├── ac_predictor.py        ← Phase 3: Transformer AC Predictor ~5M params
│   ├── train.py               ← Phase 3: training loop + TensorBoard
│   ├── cem_planner.py         ← Phase 4: CEM planning
│   ├── inference_loop.py      ← Phase 4: real-time closed-loop
│   └── baselines/
│       ├── action_cnn.py      ← baseline 1: Oh et al. 2015 style
│       └── lstm_predictor.py  ← baseline 2: GRU world model
│
├── rc-carcar/                 ← ESP32-S3 PlatformIO project (Arduino Core 3.x)
│   ├── platformio.ini         ← pioarduino fork, board esp32-s3-devkitc-1, N16R8
│   ├── specs.md               ← kết quả calibrate servo (5 lần thực nghiệm)
│   └── src/
│       ├── main.cpp           ← Serial control firmware (DONE, cần thêm WiFi/UDP)
│       └── servo_calibrate.cpp← calibration tool (đã dùng xong, commented out)
│
├── electronic_devices/        ← hardware setup docs
├── data/                      ← gitignored
│   ├── raw/                   ← recorded sessions (frames + actions.csv)
│   └── latents/               ← pre-encoded latent tensors (.pt)
├── checkpoints/               ← gitignored, model weights
├── tools/
│   └── measure_latency.py
└── notebooks/
    └── viz_latents.ipynb
```

---

## Roadmap (19 ngày đến 15/6)

### Phase 1 — Infrastructure (May 27–30)

- [x] `requirements.txt` + `.gitignore` (update)
- [ ] Tải V-JEPA 2.1 weights: `wget https://dl.fbaipublicfiles.com/vjepa2/vitl_fpc64_256.pth -P checkpoints/`
- [x] `rc-carcar/` — PlatformIO project tạo xong, Arduino Core 3.x (pioarduino)
- [x] Servo calibration — 5 lần thực nghiệm, limits: 1142–1880µs (xem `rc-carcar/specs.md`)
- [x] Firmware Serial control — arm ESC, safe limits, lệnh `s<us>` / `e<us>` qua Serial
- [ ] **Nối dây thực tế** — GPIO 5 → servo signal, GPIO 6 → ESC signal, GND chung
- [x] **Thêm WiFi + UDP vào firmware** — static IP 192.168.1.23, port 4210, watchdog 500ms, reverse state machine
- [ ] **Flash và test** — PC gửi UDP → servo quay, ESC phản hồi
- [x] `src/capture.py` — FrameCapture thread-safe, ffmpeg pipe 640×360@10fps
- [ ] `src/encoder.py` — VJEPAEncoder frozen, single-frame mode ≥10fps
- [x] `src/controller.py` — ESPController UDP, steering[-1,1] throttle[-1,1], emergency_stop()
- [ ] `tools/measure_latency.py` — đo RTT camera→encode→command

### Phase 2 — Data Collection (May 31 – June 3)

- [x] `src/recorder.py` — WASD (pynput hold-key), OpenCV live feed, 640×360 JPEG@10fps, actions.csv
- [ ] `src/offline_encode.py` — batch encode → `data/latents/*.pt`
- [ ] Thu ≥20 phút data (đa dạng: thẳng, cua, tốc độ khác nhau)
- [ ] Split: 80% train / 20% val theo session

### Phase 3 — Model Training (June 4–8)

- [ ] `src/ac_predictor.py` — Transformer 2L 8H dim=512, ~5M params
- [ ] `src/train.py` — AdamW 3e-4, CosineAnnealing 80ep, TensorBoard
- [ ] `src/baselines/action_cnn.py` — action embedding + MLP
- [ ] `src/baselines/lstm_predictor.py` — GRU 512 hidden
- [ ] Target: val MSE < 0.05, cosine sim > 0.9

### Phase 4 — CEM Planning + Eval (June 9–11)

- [ ] `src/cem_planner.py` — H=8, N=500, K=50, 4 iterations
- [ ] `src/inference_loop.py` — 5Hz control loop, Ctrl+C → stop
- [ ] `notebooks/viz_latents.ipynb` — UMAP visualization
- [ ] Online test: goal-reaching task, 5 trials/model

### Phase 5 — Paper (June 12–15)

| Section | ~trang |
|---------|--------|
| Introduction | 0.5 |
| Related Work (V-JEPA 2, DreamerV3, Oh'15) | 0.75 |
| Method (diagram + AC Predictor + CEM) | 1.5 |
| Experiments (offline table + online table + UMAP) | 2.0 |
| Discussion + Conclusion | 0.75 |

---

## Baselines So Sánh

| Model | Paper | Params | Recurrent |
|-------|-------|--------|-----------|
| Action-CNN | Oh et al. 2015 | ~10M | No |
| LSTM Predictor | — | ~3M | Yes |
| **AC Predictor (ours)** | — | ~5M | No |

---

## V-JEPA 2.1 Notes

- Weights: `https://dl.fbaipublicfiles.com/vjepa2/vitl_fpc64_256.pth`
- GitHub: `https://github.com/facebookresearch/vjepa2` (cần clone để load model)
- HuggingFace fallback: `facebook/vjepa2-vitl-fpc64-256`
- Model: ViT-L, 64 frames/clip, 256px input
- Output: spatial tokens → mean pool toàn bộ → `(B, 1024)`
- **KHÔNG bao giờ backprop qua encoder**

---

## Critical Path

1. **Firmware + wiring** — xong trước June 1 (cần để record data)
2. **V-JEPA weights** — tải ngay hôm nay (file lớn, ~3GB)
3. **Data collection** — ít nhất 20 phút, xong trước June 4
4. **Training converge** — phải xong trước June 9

---

## Daily Startup

```bash
# 1. WFB-NG
bash wfb_up.sh

# 2. Verify stream
ffplay -protocol_whitelist file,rtp,udp -fflags nobuffer -flags low_delay -framedrop -i ~/runcam.sdp

# 3. Inference (Phase 4)
python src/inference_loop.py --goal goal.jpg
```

---

## Verification Checkpoints

| Ngày | Check |
|------|-------|
| May 30 | Servo quay, ESC arm khi nhận UDP từ test script |
| June 3 | `data/latents/` có data, encoder output shape `(1, 1024)` |
| June 7 | TensorBoard val MSE < 0.05 |
| June 10 | Xe di chuyển về hướng goal image |
| June 15 | Paper PDF hoàn chỉnh |
