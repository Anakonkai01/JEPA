# RC Car Self-Driving — V-JEPA 2.1 Project Plan

## Overview

**Đề tài:** Action-Conditioned World Model for RC Car Navigation based on V-JEPA 2.1
**Novel contribution:** First evaluation của V-JEPA 2 family trên mobile robot (RC car) — Meta chỉ test trên robot arm
**Deadline: 2026-06-15**

---

## Current Status (cập nhật 2026-06-03)

### ✅ Đã xong & validate
- **Phần cứng**: ESP32-S3 + FlySky FS-i6 (mod 10ch) / FS-iA10B qua **i-BUS** + servo + ESC. Verify trên bench: lùi (Mode 3), kill switch (CH9 giữa), lái đúng chiều — OK.
- **Firmware** (`firmware/src/main.cpp`): i-BUS reader, 3 mode (CH9: RECORD/NEUTRAL/AUTO), CH10 = record on/off, **Mode-3 linear throttle**, telemetry 50Hz (packed struct), 2 watchdog (i-BUS 100ms + UDP 500ms), điều khiển LED. Servo clamp **1150–1850** (tâm đúng 1500).
- **Pipeline thu data**: `capture.py` (ffmpeg + timestamp frame), `recorder.py` (nhận telemetry + ring buffer + **bù trễ realtime** + mask LED + log), `tools/measure_latency.py`, `tools/set_led_roi.py`.
- **Đồng bộ latency = fixed-from-shade** (chiến lược chốt): L_cam **độc lập ánh sáng** (exposure/encode khoá cứng) → đo MỘT LẦN trong bóng bằng `tools/measure_latency.py` (LED tức thời về điện = đo L_cam **thuần**) → `data/camera_latency.txt` (hiện `0.092`) làm hằng số. LED realtime giữ làm **verifier trong bóng**; ngoài nắng tự rơi về fallback + báo `LED:SUN`. *(Con số "drift 55↔144ms" ghi trước đây nhiều khả năng là artifact nắng — LED bắt nhầm nền sáng — không phải L_cam trôi thật.)*
  - Re-align "thông minh" (nội suy từ `telemetry.csv` 50Hz) dồn về **offline `src/sync.py`** — hoãn, làm cùng `offline_encode.py`. Recorder đã: dump `telemetry.csv`, gate bỏ frame khi telemetry rớt (`MATCH_TOL`), chống ảo LED (`LAT_MIN/MAX`, `RISE_MIN`).

### ⚠️ Khác plan gốc
- Thu data: **bỏ WASD → FlySky i-BUS** (action liên tục thật, kill switch vật lý, link 2.4GHz riêng). Steering giờ phủ đầy [−1,1] (142 mức) thay vì 3 mức rời rạc.
- Latency: **hằng số đo-trong-bóng** (LED realtime chỉ verify; nắng không đo được mà cũng không cần — L_cam độc lập ánh sáng).

### 🔜 Việc cần làm (ưu tiên trên xuống)
1. **THU DATA XE CHẠY ĐẤT THẬT** — 2 session test mới chỉ kê cao (xe đứng yên, scene diff ~1.8/255 = ảnh tĩnh → **KHÔNG train được**). Cần xe di chuyển thật, ≥20 phút, đa dạng (thẳng/cua/tiến/lùi/tốc độ).
2. Thêm đèn — frame hơi tối (64–73/255).
3. Tắt OSD camera "Waiting for data on /dev/ttyS2" (cần cáp RJ45 + SSH `root@192.168.1.10`).
4. `src/controller.py` — sửa map Mode-3 linear cho đường AUTO (Phase 4, **chưa làm**, vẫn còn logic double-tap cũ).
5. Tải V-JEPA weights + `src/encoder.py` + `src/offline_encode.py` + `src/sync.py` (re-align offline: `t_read−L_cam` cố định + nội suy steer/throt từ `telemetry.csv`, bỏ frame telemetry-gap → `actions_synced.csv`).
6. (Tùy chọn) `tools/validate_latency_flow.py` — cross-correlation steering ↔ optical-flow **chỉ để kiểm-thô**, sau khi có session chạy đất. ⚠️ Caveat: lag đo được ≈ `L_cam + τ_xe` (động học xe), KHÔNG phải L_cam thuần → chỉ bắt lỗi lớn, không thay phép đo LED.

### 📌 Lưu ý Phase 3 (train)
- **Chuẩn hóa thang action**: throttle ~±0.1 (do D/R remote) vs steering ±1 → rescale về cùng thang trước khi đưa vào model, kẻo model coi nhẹ throttle.

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

Servo limits từ 5 lần thực nghiệm, trung bình ± 10µs safety padding — xem `firmware/specs.md`.

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
├── firmware/                 ← ESP32-S3 PlatformIO project (Arduino Core 3.x)
│   ├── platformio.ini         ← pioarduino fork, board esp32-s3-devkitc-1, N16R8
│   ├── specs.md               ← kết quả calibrate servo (5 lần thực nghiệm)
│   └── src/
│       ├── main.cpp           ← Serial control firmware (DONE, cần thêm WiFi/UDP)
│       └── servo_calibrate.cpp← calibration tool (đã dùng xong, commented out)
│
├── docs/                      ← hardware setup docs
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
- [x] `firmware/` — PlatformIO project tạo xong, Arduino Core 3.x (pioarduino)
- [x] Servo calibration — 5 lần thực nghiệm, limits: 1142–1880µs (xem `firmware/specs.md`)
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
bash scripts/wfb_up.sh

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
