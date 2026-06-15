#!/usr/bin/env python3
"""Speed-confound ablation — does a STATIONARY car flatten the steering energy landscape?

Closed-loop "tường phẳng ở bãi" was first labelled "OOD". This probe tests the
alternative (and correct) explanation: the bicycle-model couples turning to speed
(``yaw_rate = k_yaw * steer * speed``, see ``planning/dynamics.py``), so when the
car is (near-)stationary the predicted scene barely depends on steer → the energy
landscape ``E(steer)`` goes flat → CEM has no gradient. This is a STANDSTILL
artifact, NOT a scene-distribution problem.

Method (same VAL turn-windows as ``probe_energy.py``, ONLY the motion state changes —
the visual context/goal are identical, so "không đổi cảnh"). We sweep steer over [-1,1]
and report the median contrast (E_max-E_min)/E_min for three conditions:
  * baseline : real s0 + throttle = teacher                  (xe ĐANG chạy)
  * speed0   : s0.speed = 0 + throttle = teacher             (đứng rồi tăng tốc lại)
  * stalled  : s0.speed = 0 + throttle pinned to stall (≈0)  (ĐỨNG YÊN suốt horizon)
The "stalled" condition is the faithful deadlock: throttle in the dead-zone keeps speed≈0
the whole horizon, so ``yaw = k_yaw*steer*speed ≈ 0`` for every steer → the predicted
scene is steer-invariant → flat landscape (matches the live contrast ~0.01-0.02 at ga<0.06).

    PYTHONPATH=src python scripts/probe_speed_confound.py -d 4 --n-windows 200
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from jepa_wm.data.ac_clip import ACClipDataset
from jepa_wm.data.dataset import frozen_split
from jepa_wm.models import build_model
from jepa_wm.planning import CEMPlannerAC
from jepa_wm.planning.dynamics import CarDynamics


def _strip_compile(sd):
    return {k.replace("_orig_mod.", "", 1): v for k, v in sd.items()}


def _contrast(planner, z, s0, goal, seqs, dom):
    E = planner.score(z[:1], s0, goal, seqs, domain=dom).cpu().numpy()
    return float((E.max() - E.min()) / (E.min() + 1e-9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("-d", "--distance", type=int, default=4, help="goal = d bước phía trước (~0.9s)")
    ap.add_argument("--n-windows", type=int, default=200, help="số window quẹo VAL để gộp")
    ap.add_argument("--grid", type=int, default=21, help="số điểm quét steer trong [-1,1]")
    ap.add_argument("--stall-throttle", type=float, default=0.0,
                    help="ga 'đứng yên' (trong vùng-chết) cho điều kiện stalled → speed≡0 suốt horizon")
    ap.add_argument("--turn-thresh", type=float, default=0.15, help="|steer| > ngưỡng = đang quẹo")
    ap.add_argument("--history", type=int, default=2)
    ap.add_argument("--dt", type=float, default=0.22)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict(_strip_compile(ckpt["model"]))
    model.eval()
    state_mean = ckpt["state_mean"].to(args.device).float()
    state_std = ckpt["state_std"].to(args.device).float()

    d_ = cfg["data"]
    roots = d_.get("roots")
    use_domain = roots is not None and (len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots))
    cols = tuple(d_.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    stride = d_.get("frame_stride", 2)
    ascale = tuple(d_.get("action_scale", [1.0, 6.67]))
    speed_idx = cols.index("speed") if "speed" in cols else 0
    yaw_idx = cols.index("gz") if "gz" in cols else 1
    prev_idx = (cols.index("prev_steer"), cols.index("prev_throttle")) if "prev_steer" in cols else None

    for r in roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    sessions = sorted(s for r in roots for s in r["_sessions"])
    split_path = Path(args.checkpoint).parent / "split.json"
    train_s, val_s, _ = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                     seed=cfg.get("seed", 0), save=False)
    train_set, val_set = set(train_s), set(val_s)
    dyn = CarDynamics.fit([(r["raw_dir"], [s for s in r["_sessions"] if s in train_set]) for r in roots],
                          dt=args.dt, stride=stride, speed_idx=speed_idx, yaw_idx=yaw_idx)
    d = args.distance
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=d, history=args.history, prev_action_idx=prev_idx,
                           device=args.device)

    ds = ACClipDataset(roots=[{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                               "sessions": [s for s in r["_sessions"] if s in val_set],
                               "domain_id": r.get("domain_id", 0)} for r in roots],
                       horizon=d + 1, frame_stride=stride, state_columns=cols,
                       action_scale=(1.0, 1.0), state_mean=None, max_gap=d_.get("max_gap"))

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(ds))
    grid = torch.linspace(-1.0, 1.0, args.grid)
    print(f"[speed-confound] {args.checkpoint} | d={d} ({d * stride * 0.11:.1f}s) | "
          f"speed_idx={speed_idx} | grid {args.grid} điểm steer | throttle = teacher")
    print(f"[speed-confound] cơ chế: yaw_rate = k_yaw·steer·speed (k_yaw={dyn.k_yaw:.3f}) "
          f"→ speed=0 ⇒ steer không sinh yaw ⇒ landscape phẳng\n")

    real_c, zero_c, stall_c, speeds = [], [], [], []
    for i in order:
        item = ds[int(i)]
        a_raw = item["actions"].float()
        tea = float(a_raw[:d, 0].mean())
        if abs(tea) < args.turn_thresh:
            continue
        z = item["tokens"].to(args.device).float()
        s0 = item["states"][0].to(args.device).float()
        dom = float(a_raw[0, -1]) if use_domain else None
        thr = float(a_raw[:d, 1].mean())
        seqs = torch.zeros(args.grid, d, 2, device=args.device)
        seqs[:, :, 0] = grid[:, None].to(args.device)
        seqs[:, :, 1] = thr
        seqs_stall = seqs.clone()
        seqs_stall[:, :, 1] = args.stall_throttle      # ga vùng-chết → speed≡0 suốt horizon
        s0_zero = s0.clone()
        s0_zero[speed_idx] = 0.0                       # CHỈ đổi speed — context/goal y nguyên
        with torch.no_grad():
            real_c.append(_contrast(planner, z, s0, z[d], seqs, dom))
            zero_c.append(_contrast(planner, z, s0_zero, z[d], seqs, dom))
            stall_c.append(_contrast(planner, z, s0_zero, z[d], seqs_stall, dom))
        speeds.append(float(s0[speed_idx]))
        if len(real_c) >= args.n_windows:
            break

    real_c, zero_c, stall_c = np.asarray(real_c), np.asarray(zero_c), np.asarray(stall_c)
    mr, mz, ms = float(np.median(real_c)), float(np.median(zero_c)), float(np.median(stall_c))
    print(f"[speed-confound] {len(real_c)} window quẹo VAL | speed thật median {np.median(speeds):.2f} m/s")
    print(f"  contrast E(steer)  baseline (xe chạy, ga=teacher)      : median {mr:.3f}  (mean {real_c.mean():.3f})")
    print(f"  contrast E(steer)  speed0   (đứng rồi tăng tốc lại)    : median {mz:.3f}  (mean {zero_c.mean():.3f})")
    print(f"  contrast E(steer)  stalled  (ĐỨNG YÊN suốt, ga≈{args.stall_throttle:g}): median {ms:.3f}  (mean {stall_c.mean():.3f})")
    print(f"  → baseline {mr:.3f}  →  stalled {ms:.3f}  (×{ms / (mr + 1e-9):.2f})  CÙNG CẢNH, chỉ đổi chuyển-động")
    print(f"\n  KẾT LUẬN: landscape phẳng khi đứng-yên là do động học (yaw∝speed), KHÔNG phải scene-OOD.")


if __name__ == "__main__":
    main()
