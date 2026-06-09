#!/usr/bin/env python3
"""Offline goal-reaching eval for the faithful patch-token controller (VJEPA2ACCar).

The sibling ``eval_goal_reaching.py`` targets the POOLED probe (``CEMPlannerLatent`` over
a 1-D latent). This one targets the *contribution* model — ``VJEPA2ACCar`` (patch tokens +
proprioceptive state) planned with ``CEMPlannerAC`` + the ``CarDynamics`` bicycle integrator.

For held-out recorded windows we take the patch map ``d`` steps ahead as the goal and ask
CEM to reach it under the world model. Per goal-distance ``d`` we report:

  * final-patch L1 to goal for CEM / teacher (recorded actions) / random;
  * ratios CEM-vs-random (is planning non-trivial?) and CEM-vs-teacher;
  * action-recovery: |CEM's first action − the human's actual first action| in RAW units
    (steer, throttle), the most honest *offline* proxy for control quality (no car needed).

Sweeping ``d`` shows where local goal-reaching breaks down — i.e. how far apart navigation
subgoals can be before the controller can no longer reach them ("goal out of sight").

    PYTHONPATH=src python scripts/eval_goal_reaching_ac.py \
        --checkpoint checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt
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


def sessions_with_patches(patch_dir):
    return sorted(p.stem for p in Path(patch_dir).glob("*.npy"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt")
    ap.add_argument("--patch-dir", default=None, help="override (default: from ckpt cfg)")
    ap.add_argument("--raw-dir", default=None, help="override (default: from ckpt cfg)")
    ap.add_argument("--distances", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    ap.add_argument("--n-windows", type=int, default=80)
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--elite", type=int, default=16)
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--history", type=int, default=2)
    ap.add_argument("--throttle-min", type=float, default=-0.16)
    ap.add_argument("--throttle-max", type=float, default=0.15)
    ap.add_argument("--policy", default=None,
                    help="GoalPolicyPrior ckpt (train_policy_prior.py) -> warm-start CEM mu "
                         "(PiJEPA-style) + report policy-alone action recovery. Needs pooled "
                         "latents (scripts/pool_patch_latents.py).")
    ap.add_argument("--dt", type=float, default=0.22, help="clip frame-stride period (s) for CarDynamics")
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
    # Multi-root (roots: [{patch_dir, raw_dir, domain_id}]) or legacy single-root cfg.
    raw_roots = d_.get("roots")
    if raw_roots is None:
        raw_roots = [{"patch_dir": args.patch_dir or d_["patch_dir"],
                      "raw_dir": args.raw_dir or d_["raw_dir"], "domain_id": 0}]
    elif args.patch_dir or args.raw_dir:
        ap.error("--patch-dir/--raw-dir overrides only apply to single-root checkpoints")
    use_domain = len(raw_roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in raw_roots)
    cols = tuple(d_.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    stride = d_.get("frame_stride", 2)
    ascale = tuple(d_.get("action_scale", [1.0, 6.67]))

    # speed / yaw-rate positions in the model's state vector (for the dynamics integrator)
    speed_idx = cols.index("speed") if "speed" in cols else 0
    yaw_idx = cols.index("gz") if "gz" in cols else (cols.index("yaw_rate") if "yaw_rate" in cols else 1)
    prev_idx = (cols.index("prev_steer"), cols.index("prev_throttle")) if "prev_steer" in cols else None

    for r in raw_roots:
        r["_sessions"] = sessions_with_patches(r["patch_dir"])
    sessions = sorted(s for r in raw_roots for s in r["_sessions"])
    # Reuse the EXACT train/val split frozen by training (split.json next to the ckpt);
    # save=False so eval never creates one — falls back to the deterministic split if absent.
    split_path = Path(args.checkpoint).parent / "split.json"
    train_s, val_s, sinfo = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                         seed=cfg.get("seed", 0), save=False)
    train_set, val_set = set(train_s), set(val_s)
    print(f"[goal_reaching_ac] {args.checkpoint}")
    src = f"FROZEN <- {split_path}" if sinfo["frozen"] else "deterministic (no split.json found)"
    print(f"  {len(val_s)} val sessions [{src}] | state {cols} (speed@{speed_idx}, yaw@{yaw_idx}) "
          f"| domain={'on' if use_domain else 'off'} | device {args.device}")
    print(f"  action box: steer [-1,1], throttle [{args.throttle_min},{args.throttle_max}] | action_scale {ascale}")

    # fit the bicycle-model coefficients on the TRAIN sessions (held out from eval)
    fit_pairs = [(r["raw_dir"], [s for s in r["_sessions"] if s in train_set]) for r in raw_roots]
    dyn = CarDynamics.fit(fit_pairs, dt=args.dt, stride=stride,
                          speed_idx=speed_idx, yaw_idx=yaw_idx)
    print(f"  dynamics: {dyn}")

    # optional PiJEPA-style policy prior: warm-start CEM mu + report policy-alone recovery.
    policy = pooled = None
    if args.policy:
        from jepa_wm.models.policy_prior import load_policy, pooled_dir_for
        policy, _pm = load_policy(args.policy, device=args.device)
        pooled = {}
        for r in raw_roots:
            pdir = Path(pooled_dir_for(r["raw_dir"]))
            for s in r["_sessions"]:
                if s in val_set and (pdir / f"{s}.pt").exists():
                    pooled[s] = torch.load(pdir / f"{s}.pt", map_location="cpu",
                                           weights_only=False)["latents"].float()
        print(f"  policy prior: {args.policy} ({len(pooled)} val sessions with pooled latents)")
    print()

    rng = np.random.default_rng(args.seed)
    low = torch.tensor([-1.0, args.throttle_min], device=args.device)
    high = torch.tensor([1.0, args.throttle_max], device=args.device)

    hdr = (f"{'d':>3} {'CEM':>8} {'teacher':>8} {'rnd_mean':>8} {'rnd_best':>8} {'CEM/mean':>9} "
           f"{'CEM/tea':>8} {'Δsteer':>7} {'Δthrot':>7}")
    if policy is not None:
        hdr += f" {'πΔster':>7} {'πΔthrt':>7}"
    print(hdr + f" {'n':>4}")
    for d in args.distances:
        # RAW states (state_mean=None) and RAW actions (action_scale=1) — the planner applies
        # the train-time normalisation itself; tokens are always per-token LN'd by the dataset.
        # Multi-root: the dataset appends the raw domain id as the LAST action column.
        ds_kw = dict(horizon=d + 1, frame_stride=stride, state_columns=cols,
                     action_scale=(1.0, 1.0), state_mean=None, max_gap=d_.get("max_gap"))
        if use_domain:
            val_roots = [{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                          "sessions": [s for s in r["_sessions"] if s in val_set],
                          "domain_id": r.get("domain_id", 0)} for r in raw_roots]
            ds = ACClipDataset(roots=val_roots, **ds_kw)
        else:
            r0 = raw_roots[0]
            ds = ACClipDataset(r0["patch_dir"], r0["raw_dir"],
                               [s for s in r0["_sessions"] if s in val_set], **ds_kw)
        if len(ds) == 0:
            print(f"{d:>3}  (no windows)")
            continue
        idx = rng.choice(len(ds), size=min(args.n_windows, len(ds)), replace=False)
        planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                               horizon=d, n_samples=args.samples, n_elite=args.elite,
                               n_iter=args.iters, throttle_min=args.throttle_min,
                               throttle_max=args.throttle_max, history=args.history,
                               prev_action_idx=prev_idx, device=args.device)
        cem_s, tea_s, rnd_mean_s, rnd_best_s, dsteer, dthrot = [], [], [], [], [], []
        pol_dsteer, pol_dthrot = [], []
        for i in idx:
            key, start = ds.index[int(i)]
            item = ds[int(i)]
            z = item["tokens"].to(args.device).float()       # (d+1, N, D) LN'd
            s_raw = item["states"].to(args.device).float()   # (d+1, S) RAW
            a_raw = item["actions"].to(args.device).float()  # (d+1, 2|3) RAW (+domain col)
            dom = float(a_raw[0, -1]) if use_domain else None
            a_raw = a_raw[:, :2]
            z0 = z[:1]                                        # (1, N, D) context frame
            goal = z[d]                                       # (N, D)
            s0_raw = s_raw[0]                                 # (S,)
            teacher = a_raw[:d].unsqueeze(0)                  # (1, d, 2) the d real transitions

            mu0 = None
            if policy is not None and key in pooled:
                zp = pooled[key][start].to(args.device).unsqueeze(0)
                zgp = pooled[key][start + d * stride].to(args.device).unsqueeze(0)
                s_z = ((s0_raw - state_mean) / state_std).unsqueeze(0)
                with torch.no_grad():
                    prop = policy(zp, zgp, s_z, dom)[0]      # RAW (2,)
                mu0 = prop
                pol_dsteer.append(abs(float(prop[0] - teacher[0, 0, 0])))
                pol_dthrot.append(abs(float(prop[1] - teacher[0, 0, 1])))

            _, info = planner.plan(z0, s0_raw, goal, return_info=True, domain=dom, mu_init=mu0)
            cem_seq = info["sequence"].to(args.device)
            cem_s.append(info["score"])
            tea_s.append(float(planner.score(z0, s0_raw, goal, teacher, domain=dom)[0]))
            rnd = low + (high - low) * torch.rand(args.samples, d, 2, device=args.device)
            rsc = planner.score(z0, s0_raw, goal, rnd, domain=dom)
            rnd_mean_s.append(float(rsc.mean()))
            rnd_best_s.append(float(rsc.min()))
            dsteer.append(abs(float(cem_seq[0, 0] - teacher[0, 0, 0])))
            dthrot.append(abs(float(cem_seq[0, 1] - teacher[0, 0, 1])))
        cm, tm = np.median(cem_s), np.median(tea_s)
        rmean, rbest = np.median(rnd_mean_s), np.median(rnd_best_s)
        line = (f"{d:>3} {cm:>8.4f} {tm:>8.4f} {rmean:>8.4f} {rbest:>8.4f} "
                f"{cm/max(rmean,1e-9):>9.2f} {cm/max(tm,1e-9):>8.2f} "
                f"{np.median(dsteer):>7.3f} {np.median(dthrot):>7.3f}")
        if policy is not None:
            line += (f" {np.median(pol_dsteer):>7.3f} {np.median(pol_dthrot):>7.3f}"
                     if pol_dsteer else " " * 16)
        print(line + f" {len(idx):>4}")

    print("\nĐọc: CEM/mean < 1 = planning có ích (hơn lái ngẫu nhiên); CEM/tea ~1 = sát người lái.")
    print("Δsteer/Δthrot nhỏ = CEM khôi phục được hành động người (proxy điều khiển tốt, RAW units).")
    print("Cả hai xấu đi khi d tăng = giới hạn tầm-với của controller (goal càng xa càng khó).")


if __name__ == "__main__":
    main()
