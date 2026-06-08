#!/usr/bin/env python3
"""Offline goal-reaching eval for the frozen-encoder controller (vjepa_ac).

For held-out recorded windows, take the latent ``d`` steps ahead as the goal and
ask CEM to reach it under the world model. We report, per goal-distance ``d``:

  * final-latent MSE to goal for CEM / teacher (recorded actions) / random;
  * ratios CEM-vs-random (is planning non-trivial?) and CEM-vs-teacher;
  * action-recovery: |CEM's first action - the human's actual first action|, the
    most honest *offline* proxy for control quality (no car needed).

Sweeping ``d`` quantifies exactly where local goal-reaching breaks down — i.e. how
far apart navigation subgoals can be before the controller can no longer reach
them ("goal out of sight"). Works on the existing KDS checkpoint now; point
``--checkpoint``/``--latents-dir``/``--raw-dir`` at the TowerPro model later.

    python scripts/eval_goal_reaching.py --checkpoint checkpoints/vjepa_ac/best.pt
"""
from __future__ import annotations

import argparse

import numpy as np
import torch

from jepa_wm.data import LatentTransitionDataset, split_sessions
from jepa_wm.data.dataset import list_sessions  # noqa: F401  (kept for parity)
from jepa_wm.models import build_model
from jepa_wm.planning import CEMPlannerLatent


def sessions_with_latents(latents_dir):
    from pathlib import Path
    return sorted(p.stem for p in Path(latents_dir).glob("*.pt"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac/best.pt")
    ap.add_argument("--latents-dir", default=None, help="override (default: from ckpt cfg)")
    ap.add_argument("--raw-dir", default=None, help="override (default: from ckpt cfg)")
    ap.add_argument("--distances", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32])
    ap.add_argument("--n-windows", type=int, default=120)
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--elite", type=int, default=16)
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--throttle-min", type=float, default=-0.16)
    ap.add_argument("--throttle-max", type=float, default=0.15)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict(ckpt["model"]); model.eval()
    mean = ckpt["lat_mean"].to(args.device).float()
    std = ckpt["lat_std"].to(args.device).float()
    ascale = cfg["data"].get("action_scale") or [1.0, 1.0]   # throttle normalization used at train

    lat_dir = args.latents_dir or cfg["data"]["latents_dir"]
    raw_dir = args.raw_dir or cfg["data"]["raw_dir"]
    sessions = sessions_with_latents(lat_dir)
    _, val = split_sessions(sessions, val_frac=cfg["data"].get("val_frac", 0.2), seed=cfg.get("seed", 0))
    print(f"[goal_reaching] {args.checkpoint} | {len(val)} val sessions | device {args.device}")
    print(f"  action box: steering [-1,1], throttle [{args.throttle_min},{args.throttle_max}]\n")

    # action box in the model's (scaled) units; throttle gets the same scale as training
    low = [-1.0, args.throttle_min * ascale[1]]
    high = [1.0, args.throttle_max * ascale[1]]
    rng = np.random.default_rng(args.seed)

    print(f"{'d':>3} {'CEM':>8} {'teacher':>8} {'rnd_mean':>8} {'rnd_best':>8} {'CEM/mean':>9} "
          f"{'Δsteer':>7} {'Δthrot':>7} {'n':>4}")
    for d in args.distances:
        ds = LatentTransitionDataset(lat_dir, raw_dir, sessions=val, horizon=d, action_scale=ascale)
        if len(ds) == 0:
            print(f"{d:>3}  (no windows)"); continue
        idx = rng.choice(len(ds), size=min(args.n_windows, len(ds)), replace=False)
        planner = CEMPlannerLatent(model, horizon=d, n_samples=args.samples, n_elite=args.elite,
                                   n_iter=args.iters, action_dim=2, action_low=low, action_high=high,
                                   device=args.device)
        cem_s, tea_s, rnd_mean_s, rnd_best_s, dsteer, dthrot = [], [], [], [], [], []
        for i in idx:
            item = ds[int(i)]
            if "latents" in item:                                            # horizon > 1
                raw_lat, raw_act = item["latents"], item["actions"]
            else:                                                            # horizon == 1
                raw_lat = torch.stack([item["s_t"], item["s_next"]])         # (2, D)
                raw_act = item["a_t"].unsqueeze(0)                           # (1, A)
            lat = ((raw_lat.to(args.device).float() - mean) / std)           # (d+1, D)
            acts = raw_act.to(args.device).float()                           # (d, A)
            s0, goal = lat[0], lat[d]
            _, info = planner.plan(s0, goal, return_info=True)
            cem_seq = info["sequence"].to(args.device)
            cem_s.append(info["score"])
            tea_s.append(float(planner.score(s0, goal, acts.unsqueeze(0))[0]))
            lo = torch.tensor(low, device=args.device); hi = torch.tensor(high, device=args.device)
            rnd = lo + (hi - lo) * torch.rand(args.samples, d, 2, device=args.device)
            rsc = planner.score(s0, goal, rnd)
            rnd_mean_s.append(float(rsc.mean()))                             # acting randomly
            rnd_best_s.append(float(rsc.min()))                             # best-of-N random search
            # report action-recovery in REAL units (undo the training scale)
            dsteer.append(abs(float(cem_seq[0, 0] - acts[0, 0])) / ascale[0])
            dthrot.append(abs(float(cem_seq[0, 1] - acts[0, 1])) / ascale[1])
        cm, tm = np.median(cem_s), np.median(tea_s)
        rmean, rbest = np.median(rnd_mean_s), np.median(rnd_best_s)
        print(f"{d:>3} {cm:>8.4f} {tm:>8.4f} {rmean:>8.4f} {rbest:>8.4f} {cm/max(rmean,1e-9):>9.2f} "
              f"{np.median(dsteer):>7.3f} {np.median(dthrot):>7.3f} {len(idx):>4}")

    print("\nĐọc: CEM/rand < 1 = planning có ích; Δsteer/Δthrot nhỏ = CEM khôi phục được")
    print("hành động người lái (proxy điều khiển tốt). Cả hai xấu đi khi d tăng = giới hạn tầm với.")


if __name__ == "__main__":
    main()
