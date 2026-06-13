#!/usr/bin/env python3
"""DECISIVE offline test for the recovery augmentation: does the recovery-trained policy
produce a GRADED CORRECTIVE steer when shown a synthetic lateral-offset view, where the
BASELINE policy does not? (Held-out VAL sessions.)

For each val anchor we feed both policies the SAME goal/state but swap z_t for the offset
latents (scripts/pool_recovery_latents.py: shift +s = drift RIGHT). Correct recovery =
steer DECREASES (turns left) as shift goes +; the curve should be monotonic and centred near
the normal (shift 0) prediction. Baseline is expected ~flat (the failure: no recovery signal
survives in the pooled latent / wasn't trained for it).

CAVEAT this CANNOT prove on-car transfer (synthetic shift is a proxy for real offset; no
renderer offline). It proves the policy LEARNED a corrective mapping — the on-car probe
(lift car left/right, read steer sign) is the ground truth.

    PYTHONPATH=src python scripts/eval_recovery_response.py \
        --baseline checkpoints/policy_prior_cd4/best.pt \
        --recovery checkpoints/policy_recovery_cd4/best.pt
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, "scripts")
from jepa_wm.data.dataset import frozen_split
from jepa_wm.data.state import load_state
from jepa_wm.models.policy_prior import load_policy, pooled_dir_for
from train_policy_prior import load_split_and_roots
from train_policy_recovery import recovery_dir_for


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wm", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("--baseline", default="checkpoints/policy_prior_cd4/best.pt")
    ap.add_argument("--recovery", default="checkpoints/policy_recovery_cd4/best.pt")
    ap.add_argument("--goal-d", type=int, default=2, help="goal = d steps ahead (control-target scale)")
    ap.add_argument("--n", type=int, default=8000, help="val anchors to sample")
    args = ap.parse_args()

    ckpt = torch.load(args.wm, map_location="cpu", weights_only=False)
    cfg, roots, sessions = load_split_and_roots(ckpt)
    d_ = cfg["data"]; cols = tuple(d_["state_columns"]); stride = d_.get("frame_stride", 2)
    sm, ss = ckpt["state_mean"].float(), ckpt["state_std"].float()
    use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)
    _, val_s, _ = frozen_split(Path(args.wm).parent / "split.json", sessions,
                               val_frac=d_.get("val_frac", 0.2), seed=cfg.get("seed", 0), save=False)
    val_set = set(val_s)

    Z, ZG, ST, DOM, BASE, AUG = [], [], [], [], [], []
    shifts = None
    for r in roots:
        dom = float(r.get("domain_id", 0))
        rec_dir = Path(recovery_dir_for(r["raw_dir"]))
        for s in r["_sessions"]:
            if s not in val_set or not (rec_dir / f"{s}.pt").exists():
                continue
            z = torch.load(Path(r["pooled_dir"]) / f"{s}.pt", weights_only=False)["latents"].float()
            st, fidx = load_state(Path(r["raw_dir"]) / s, cols)
            with open(Path(r["raw_dir"]) / s / "actions_synced.csv") as f:
                act = np.array([[float(x["steering"]), float(x["throttle"])] for x in csv.DictReader(f)],
                               dtype=np.float32)
            st = ((torch.from_numpy(st) - sm) / ss).float()
            rb = torch.load(rec_dir / f"{s}.pt", weights_only=False)
            aug = rb["aug"].float(); shifts = rb["shifts"].tolist()
            n = z.shape[0]
            for i in range(n - args.goal_d * stride):
                Z.append(z[i]); ZG.append(z[i + args.goal_d * stride]); ST.append(st[i])
                DOM.append(dom); BASE.append(act[i, 0]); AUG.append(aug[i])
    Z = torch.stack(Z); ZG = torch.stack(ZG); ST = torch.stack(ST)
    DOM = torch.tensor(DOM); BASE = torch.tensor(BASE); AUG = torch.stack(AUG)   # (M,n_shifts,D)
    M = Z.shape[0]
    idx = np.random.default_rng(0).choice(M, min(args.n, M), replace=False)
    Z, ZG, ST, DOM, BASE, AUG = Z[idx], ZG[idx], ST[idx], DOM[idx], BASE[idx], AUG[idx]
    print(f"[resp] {len(idx)} val anchors | goal-d {args.goal_d} | shifts {shifts} (+ = drift RIGHT → want steer ↓/left)")

    def predict(model, z):
        with torch.no_grad():
            out = model(z, ZG, ST, DOM if use_domain else None)
            return out[:, 0].numpy(), out[:, 1].numpy()      # steer, throttle

    rows = [("baseline", args.baseline), ("recovery", args.recovery)]
    for name, path in rows:
        if not Path(path).exists():
            print(f"  [{name}] {path} MISSING — skip"); continue
        model, _ = load_policy(path, device="cpu")
        base_st, base_th = predict(model, Z)             # normal (shift 0)
        print(f"\n── {name} ── normal: steer {base_st.mean():+.3f}  throttle {base_th.mean():+.3f}")
        print(f"   {'shift':>6} {'steer':>8} {'Δsteer':>8} {'sign':>5} {'throttle':>9} {'Δthr':>7}")
        deltas = []
        for k, s in enumerate(shifts):
            p, pth = predict(model, AUG[:, k])
            d = (p - base_st).mean(); dth = (pth - base_th).mean()
            deltas.append((s, d))
            ok = "✓" if (np.sign(d) == -np.sign(s)) else "✗"
            print(f"   {s:>+6d} {p.mean():>+8.3f} {d:>+8.3f} {ok:>5} {pth.mean():>+9.3f} {dth:>+7.3f}")
        # monotonic corrective slope: regress Δsteer on shift (want NEGATIVE slope)
        sv = np.array([s for s, _ in deltas]); dv = np.array([d for _, d in deltas])
        slope = np.polyfit(sv, dv, 1)[0]
        mono = all(dv[i] <= dv[i-1] + 1e-4 for i in range(1, len(dv)))  # non-increasing with shift
        big = abs(dv[sv.argmax()])                       # |Δsteer| at largest +shift
        print(f"   slope(Δsteer/shift) = {slope:+.4f} (want <0) | monotone-corrective: {mono} | "
              f"|Δsteer|@+{int(sv.max())} = {big:.3f} (want ≥0.25 để kéo về thật)")


if __name__ == "__main__":
    main()
