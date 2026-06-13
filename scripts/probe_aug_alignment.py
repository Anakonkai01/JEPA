#!/usr/bin/env python3
"""H-A: is the SYNTHETIC lateral-shift direction (recovery augment) aligned with how the pooled
latent REALLY moves when the camera turns? If orthogonal, the augmentation trains the wrong
direction → recovery won't transfer to the car. (Uses pooled + recovery latents + gyro — all
SMALL files, no patch-cache read, so it runs alongside pool_recovery_latents.)

Idea: when the car yaws, the scene shifts horizontally in view ≈ what a synthetic token-shift does.
For frames i where the car is yawing, real_delta = pool[i+k]-pool[i]; compare its cosine to the
synthetic right/left shift deltas (aug[i,+12]-pool[i]) / (aug[i,-12]-pool[i]). A clean result:
yaw-one-way aligns with +shift, yaw-other-way with -shift, both |cos| clearly >0; and STRAIGHT
motion (control) aligns far LESS (forward motion isn't a horizontal shift).

    PYTHONPATH=src python scripts/probe_aug_alignment.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from jepa_wm.data.state import load_state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pooled", default="data/latents_towerpro")
    ap.add_argument("--recovery", default="data/latents_towerpro_recovery")
    ap.add_argument("--raw", default="data/raw_towerpro")
    ap.add_argument("-k", type=int, default=2, help="frame gap for real delta")
    ap.add_argument("--yaw-thr", type=float, default=0.3, help="|gz| rad/s to count as yawing")
    ap.add_argument("--max-sessions", type=int, default=60)
    args = ap.parse_args()

    cols = ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]
    gz_i, sp_i = cols.index("gz"), cols.index("speed")
    rec_files = sorted(Path(args.recovery).glob("*.pt"))[:args.max_sessions]
    if not rec_files:
        print("no recovery latents yet — run pool_recovery_latents.py first"); return

    # accumulate (yaw, speed, cosR, cosL)
    YAW, SPD, COSR, COSL = [], [], [], []
    shifts = None
    used = 0
    for rf in rec_files:
        s = rf.stem
        pf = Path(args.pooled) / f"{s}.pt"
        if not pf.exists():
            continue
        try:
            pool = torch.load(pf, weights_only=False)["latents"].float()
            rb = torch.load(rf, weights_only=False)
            aug = rb["aug"].float(); shifts = rb["shifts"].tolist()
            st, fidx = load_state(Path(args.raw) / s, tuple(cols))
        except Exception:
            continue
        if pool.shape[0] != aug.shape[0] or len(fidx) != pool.shape[0]:
            continue
        st = torch.from_numpy(st).float()
        iR, iL = shifts.index(max(shifts)), shifts.index(min(shifts))   # +12, -12
        n = pool.shape[0]
        for i in range(n - args.k):
            real = pool[i + args.k] - pool[i]
            if real.norm() < 1e-6:
                continue
            sR = aug[i, iR] - pool[i]; sL = aug[i, iL] - pool[i]
            YAW.append(float(st[i:i + args.k, gz_i].mean()))
            SPD.append(float(st[i:i + args.k, sp_i].mean()))
            COSR.append(float(F.cosine_similarity(real, sR, dim=0)))
            COSL.append(float(F.cosine_similarity(real, sL, dim=0)))
        used += 1
    YAW = np.array(YAW); SPD = np.array(SPD); COSR = np.array(COSR); COSL = np.array(COSL)
    print(f"[align] {used} sessions, {len(YAW)} frame-pairs, k={args.k}, shifts={shifts}")
    print(f"[align] |gz| dist: p50 {np.percentile(np.abs(YAW),50):.3f} p90 {np.percentile(np.abs(YAW),90):.3f} rad/s")

    def report(name, m):
        if m.sum() < 20:
            print(f"  {name:>22}: n={m.sum()} (too few)"); return
        print(f"  {name:>22}: n={m.sum():5d}  cos(real, synthRIGHT+12)={COSR[m].mean():+.3f}  "
              f"cos(real, synthLEFT-12)={COSL[m].mean():+.3f}")
    yr = args.yaw_thr
    print("── alignment of REAL scene-motion with SYNTHETIC shift, by motion type ──")
    report("yaw RIGHT (gz>+thr)", YAW > yr)
    report("yaw LEFT  (gz<-thr)", YAW < -yr)
    report("STRAIGHT (|gz|<.1,mv)", (np.abs(YAW) < 0.1) & (SPD > 0.2))
    print("\nĐọc: nếu yaw-phải lệch synthRIGHT > synthLEFT (và yaw-trái ngược lại), VÀ cả hai > STRAIGHT")
    print("     → synthetic shift ĐI ĐÚNG TRỤC chuyển-động-ngang thật → augment có cơ-sở vật-lý.")
    print("     Nếu cosR≈cosL≈0 hoặc ≈ STRAIGHT → synthetic shift là trục LẠ → recovery khó transfer.")


if __name__ == "__main__":
    main()
