# Action-Conditioned World Model for RC-Car Navigation (V-JEPA 2.1)

Freeze a pretrained **V-JEPA 2.1** ViT-L encoder and train a small action-conditioned
predictor (~5M params) that learns *which action causes which visual change* in latent
space, then use **CEM planning** to navigate toward a goal image.

**Novel contribution:** first evaluation of the V-JEPA 2 family on a mobile robot (RC car) —
Meta only tested on robot arms. **Deadline: 2026-06-15.**

Two world models are trained and compared on the same frozen-latent dataset:
- **`vjepa_ac`** — single-step Action-Conditioned predictor (the main contribution).
- **`leworldmodel`** — recurrent latent dynamics baseline (GRU over V-JEPA latents).

---

## Repository layout

```
.
├── src/jepa_wm/        # ML package (pip install -e .)
│   ├── data/           # dataset.py, sync.py  (frame↔action re-pairing, δ_cam-corrected)
│   ├── models/         # encoders/vjepa.py (frozen), ac_predictor.py, leworldmodel.py, baselines/
│   ├── engine/         # encode.py (offline latents), train.py, losses.py
│   ├── planning/       # cem.py: CEMPlanner (LeWM) + CEMPlannerLatent (vjepa_ac)
│   ├── nav/            # graph.py: TopoGraph — visual subgoal navigation (place+GPS, action-agnostic)
│   └── utils/          # config.py (YAML + CLI overrides)
├── configs/            # YAML experiment configs (data/ model/ train/)
├── scripts/            # CLI: sync_dataset, encode_dataset, train, evaluate,
│                       #   build_graph, eval_navigation, eval_goal_reaching, viz_route
├── robot/              # data-collection + embedded rig (see robot/README is docs/)
│   ├── firmware/       # ESP32-S3 PlatformIO (car + dongle)
│   ├── android/        # onboard phone app (CameraX + USB telemetry recorder)
│   ├── capture/        # capture.py, controller.py, recorder.py
│   ├── tools/          # dongle_link, measure_latency, set_led_roi, pc_receiver, make_video, ...
│   ├── keys/ setup/ scripts/   # WFB keys, udev rule, wfb_up.sh
│   └── docs/           # hardware setup docs
├── docs/               # PLAN.md, HANDOFF.md, DATA_COLLECTION.md
├── data/               # gitignored — synced via Drive (rclone copy data/raw gdrive:JEPA/raw)
├── checkpoints/        # gitignored — model weights
├── notebooks/
└── CLAUDE.md           # agent / project guide (read first)
```

The repo has **two subsystems**: the **ML research** code (root, `src/jepa_wm/`) and the
**robot rig** (`robot/`, used to collect data — see `docs/DATA_COLLECTION.md`). They share
only the recorded data under `data/`.

---

## Setup

```bash
pip install -e .            # ML package + training deps
pip install -e .[robot]     # + pyserial/pynput for the data-collection rig
```

## Training pipeline

```bash
# 1. Re-pair frames with actions/IMU at true scene time (δ_cam-corrected).
python scripts/sync_dataset.py                 # -> actions_synced.csv + imu_synced.csv per session

# 2. Pre-encode every frame through the frozen V-JEPA encoder (once).
python scripts/encode_dataset.py --config configs/data/default.yaml   # -> data/latents/*.pt

# 3. Train a world model.
python scripts/train.py --config configs/train/default.yaml configs/model/vjepa_ac.yaml
python scripts/train.py --config configs/train/default.yaml configs/model/leworldmodel.yaml \
                        --set train.lr=1e-4 train.epochs=120

# 4. Evaluate (offline latent metrics; online goal-reaching is Phase 4).
python scripts/evaluate.py --config configs/model/vjepa_ac.yaml --checkpoint checkpoints/vjepa_ac/best.pt
```

```
frame_t   → V-JEPA encoder (FROZEN) → s_t   ─┐
action_t  ───────────────────────────────────→ AC Predictor → ŝ_{t+1}
frame_{t+1}→ V-JEPA encoder (FROZEN) → s_{t+1}  (ground truth)
Loss = MSE(ŝ, s_{t+1}) + 0.5·(1 − cos(ŝ, s_{t+1}))
```
**Never backprop through the encoder.** Pre-encoding the dataset once is the key
optimization (~50–100× speedup vs. encoding during training).

## Status

Current dataset: ~29 usable sessions / 55k frames (onboard-phone rig). Model/training
modules are **scaffolded** (`engine.encode`, `engine.train`, `data.dataset`, V-JEPA loading
are stubs marked `TODO(jepa_wm)`); the next step is wiring the encoder + dataset. See
`docs/HANDOFF.md` for live status and `docs/PLAN.md` for the roadmap.
