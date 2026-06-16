#!/usr/bin/env python3
"""Clear "model picks the same steer as the human" figure (replaces the hard-to-read 3-panel
energy-landscape figure) — NO GPU. Reads a precomputed demo.json (scripts/demo_precompute.py).

Two panels:
  (A) scatter: human steer (x) vs model argmin-energy steer (y) on TURN frames, colored by
      sign-agree; the closer to the diagonal, the better. Title shows sign% and median |Δsteer|.
  (B) time series over the session: human steer vs model steer — visual proof the planner
      tracks the human's steering through the turns.

    PYTHONPATH=src python scripts/plot_steer_tracking.py \
        --demo data/demo/session_20260607_162959/demo.json \
        --out docs/report/figures/fig_steer_tracking.png
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default="data/demo/session_20260607_162959/demo.json")
    ap.add_argument("--out", default="docs/report/figures/fig_steer_tracking.png")
    ap.add_argument("--win", type=int, default=260, help="#frames shown in the time-series panel")
    args = ap.parse_args()

    d = json.load(open(args.demo))
    fr = d["frames"]
    hs = np.array([f["human_steer"] for f in fr])
    ms = np.array([f["model_steer"] for f in fr])
    turn = np.array([bool(f.get("is_turn")) for f in fr])

    th = hs[turn]; tm = ms[turn]
    sign_ok = np.sign(th) == np.sign(tm)
    sign_pct = 100 * sign_ok.mean()
    dmed = np.median(np.abs(tm - th))

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(11.5, 4.4))

    # ---- (A) scatter ----
    axA.plot([-1, 1], [-1, 1], "k--", lw=1, alpha=0.6, zorder=1)
    axA.axhline(0, color="#aaaaaa", lw=0.8); axA.axvline(0, color="#aaaaaa", lw=0.8)
    axA.scatter(th[sign_ok], tm[sign_ok], s=14, c="#2e7d32", alpha=0.5, label="sign-correct", zorder=3)
    axA.scatter(th[~sign_ok], tm[~sign_ok], s=18, c="#d9534f", alpha=0.7, label="wrong sign", zorder=4)
    axA.set_xlabel("HUMAN steer (teacher)", fontsize=10)
    axA.set_ylabel("MODEL steer (argmin-energy)", fontsize=10)
    axA.set_xlim(-1.05, 1.05); axA.set_ylim(-1.05, 1.05)
    axA.set_title(f"(A) Model steers the same way as the human\nsign-correct {sign_pct:.1f}% · median |Δ| {dmed:.3f}",
                  fontsize=10)
    axA.legend(fontsize=8.5, loc="upper left")
    axA.set_aspect("equal")

    # ---- (B) time series ----
    n = min(args.win, len(fr))
    # pick the most active window (max steering variance) for clarity
    if len(fr) > n:
        best_i, best_v = 0, -1
        for i in range(0, len(fr) - n, 10):
            v = np.var(hs[i:i + n])
            if v > best_v:
                best_v, best_i = v, i
        sl = slice(best_i, best_i + n)
    else:
        sl = slice(0, n)
    t = np.arange(n)
    axB.plot(t, hs[sl], color="#2e7d32", lw=2.0, label="HUMAN steer")
    axB.plot(t, ms[sl], color="#0275d8", lw=1.4, alpha=0.85, label="MODEL steer")
    axB.axhline(0, color="#aaaaaa", lw=0.8)
    axB.set_xlabel("frame (within session)", fontsize=10)
    axB.set_ylabel("steering  [−1 left … +1 right]", fontsize=10)
    axB.set_ylim(-1.1, 1.1)
    axB.set_title("(B) Model tracks the human's steering through the turns", fontsize=10)
    axB.legend(fontsize=8.5, loc="upper right")
    axB.grid(alpha=0.2)

    fig.suptitle(f"Planner picks steering matching the human — VAL session {d['session'].split('_')[-1]} "
                 f"(goal ~{d.get('goal_lead_s', 0.9):.1f}s ahead)", fontsize=10.5, y=1.02)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
