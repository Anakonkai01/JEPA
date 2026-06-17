# Action-Conditioned World Model for RC-Car Navigation (V-JEPA 2.1)

Freeze a pretrained **V-JEPA 2.1 ViT-L 384** encoder, train a small
**AC Predictor (≈ 39.2M params)** that learns *which action causes which visual change*
in latent space, then use **CEM planning** to navigate toward a goal image on a real
outdoor RC car.

**Context:** first experiment of the V-JEPA 2 family on a mobile robot — Meta's published
evaluations target fixed robot arms (tabletop scenes); the outdoor RC car is a harder
robustness regime (lighting shift, heading change, lateral drift).

Full results and analysis: [`docs/report/2_REPORT_FULL.md`](docs/report/2_REPORT_FULL.md)

---

## Results (three evaluation tiers)

| Tier | Setting | Key result |
|---|---|---|
| **Tier 1** — Offline dynamics | Rollout vs identity baseline | **rollout@1 / identity = 0.744** (beats "still scene"); steer sign-turn **95%**, throttle want-forward **83%** |
| **Tier 2** — Open-loop planner (joint steer × throttle) | 3 held-out VAL sessions, 893 turning frames | Steering sign-turn **94.2%**, median deviation **0.118**; throttle deviation **0.033**; model self-chooses forward throttle **92%** |
| **Tier 3** — Outdoor closed-loop | ~10 real runs, 1 park environment | Tracks first half, then veers — primary cause: **localization descriptor** (mean-pooled latent + cosine) not invariant to lighting/heading shift |

---

## Repository layout

```
.
├── src/jepa_wm/        # ML package (pip install -e .)
│   ├── data/           # dataset.py, sync.py  (frame↔action pairing, δ_cam-corrected)
│   ├── models/         # encoders/vjepa.py (frozen), vjepa2_ac_car.py (AC predictor), baselines/
│   ├── engine/         # encode.py (offline latents), train_ac_car.py
│   ├── planning/       # cem.py (CEM + bicycle model), dynamics.py
│   └── utils/
├── configs/            # YAML experiment configs
├── scripts/            # CLI entrypoints (see Training pipeline below)
├── robot/              # data-collection + embedded rig
│   ├── firmware/       # ESP32-S3 PlatformIO (car env + dongle env)
│   ├── android/        # onboard phone app (CameraX + USB telemetry recorder)
│   ├── capture/        # capture.py, recorder.py, controller.py
│   ├── tools/          # pc_receiver, make_video, pull_drive, set_led_roi, …
│   └── docs/           # hardware setup docs
├── docs/
│   ├── report/         # 2_REPORT_FULL.md — full written report
│   ├── HANDOFF.md      # live session status (read first)
│   └── PLAN.md         # roadmap
├── web/demo.html       # open-loop demo web player (steer×throttle heatmap)
├── data/               # gitignored — synced via rclone/Drive
└── checkpoints/        # gitignored — model weights
```

---

## Hardware & data collection

- **Car:** off-road RC chassis, ESP32-S3 controller, TowerPro MG946R servo, Hobbywing 8BL150 ESC
- **Onboard recorder:** Samsung A42 5G — ultrawide camera + GPS + IMU, reads ESP32 telemetry over USB;
  frames and telemetry share **one phone clock** → clean synchronization
- **Dataset:** **209 sessions · 228,511 frames · 7.43 hours** of real outdoor driving
  (KDS domain: 28 ss / 1.73 h; TowerPro domain: 181 ss / 5.71 h)
- **Split:** session-level 80/20, seed 0 → **167 train / 42 val**

---

## Setup

```bash
pip install -e .            # ML package + training deps
pip install -e .[robot]     # + pyserial/pynput for the data-collection rig
```

## Training pipeline

```bash
# 1. Re-pair frames with actions/IMU at true scene time (δ_cam-corrected)
python scripts/sync_dataset.py          # → actions_synced.csv + imu_synced.csv per session

# 2. Pre-encode every frame through the frozen V-JEPA encoder once
python scripts/encode_dataset.py        # → data/latents/*.pt  (~50-100× training speedup)

# 3. Train the AC predictor
python scripts/train_ac_car.py          # deployment checkpoint: checkpoints/vjepa_ac_car_cd4/

# 4. Offline evaluation (Tier 1)
python scripts/eval_ratio_ac.py         # rollout@k / identity
python scripts/probe_energy.py --turn-only -d 4 --n-windows 300 --with-throttle

# 5. Open-loop joint planner demo (Tier 2)
python scripts/demo_precompute.py <session> -d 4   # precompute 15×9 grid per frame
python scripts/demo_web.py                          # serve web player at :8070

# 6. Closed-loop inference (Tier 3)
python scripts/inference_loop.py        # phone streams → PC plans → ESP32 drives
```

**Key optimization:** pre-encoding the 228k-frame dataset through V-JEPA offline (once) and
reading latents directly during training avoids V-JEPA forward passes → **~50–100× speedup**.

---

## Model

| | Meta V-JEPA 2-AC (reference) | Ours |
|---|---|---|
| Encoder | frozen V-JEPA 2 ViT | frozen **V-JEPA 2.1 ViT-L 384** |
| Predictor depth / width | ~24 layers / ~300M | **12 layers / 512 / 39.2M** |
| State | 7-D arm pose (sub-mm proprioception) | **12-D** (GPS speed + gyro + accel + rotvec + prev-action) |
| Action | 7-D Δ end-effector | **3-D** [steer, throttle, domain_id] |
| Pos-embedding | 3D-RoPE | learned (temporal + token-type) |
| Dynamics for CEM | arm kinematics | **bicycle model** fit from car data |

Deployment checkpoint: `checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt`

---

## Key findings

- **The world model works offline (Tiers 1–2):** the AC predictor learns action-conditioned
  dynamics on both steering and throttle axes; the CEM planner matches expert steering 94% of
  the time on held-out video, with a median deviation of only 0.12 on the [−1,1] scale.
- **Closed-loop failure is localization, not representation:** the V-JEPA patch-L1 control
  stage is lighting-robust (< 5% change sun→cloud); the failure is in the **mean-pooled
  cosine localization descriptor** used for goal-popping, which collapses when lighting or
  heading shifts between teach time and run time.
- **Fix:** learn a lighting/heading-invariant descriptor (small head on frozen V-JEPA,
  trained cross-session — the 209-session dataset already contains same-place-different-time
  pairs).

---

## Live status

See [`docs/HANDOFF.md`](docs/HANDOFF.md) for the current session state.
See [`docs/report/2_REPORT_FULL.md`](docs/report/2_REPORT_FULL.md) for the full report.
