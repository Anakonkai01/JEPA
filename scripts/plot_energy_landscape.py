#!/usr/bin/env python3
"""Redraw the energy-landscape figure for the report from a precomputed demo.json
(scripts/demo_precompute.py output) — NO GPU needed.

Three panels, one held-out VAL session:
  (A) a few BOLD E(steer) curves at turning frames — the valley bottom (argmin, ●) sits on
      the side the human turned (dotted line); red = human turned left, blue = right.
  (B) scatter argmin-E (model) vs human steer over all turning frames (green = same sign).
  (C) full-session heatmap time × steer of the (column-normalised) energy, with the human and
      model steer traces overlaid — the dark valley tracks the human.

    PYTHONPATH=src python scripts/plot_energy_landscape.py \
        --demo data/demo/session_20260607_162959/demo.json \
        --out docs/report/figures/fig_energy_landscape.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default="data/demo/session_20260607_162959/demo.json")
    ap.add_argument("--out", default="docs/report/figures/fig_energy_landscape.png")
    ap.add_argument("--n-curves", type=int, default=5)
    args = ap.parse_args()

    d = json.loads(Path(args.demo).read_text())
    grid = np.asarray(d["grid"], float)                 # steer sweep points
    frames = d["frames"]
    s = d["summary"]
    sess = d["session"]; lead = d.get("goal_lead_s", round(d["d"] * d["stride"] * 0.11, 2))

    turns = [f for f in frames if f.get("is_turn") and f.get("E")]
    # pick clear example curves: highest contrast, balanced left/right turns
    left = sorted([f for f in turns if f["human_steer"] < 0], key=lambda f: -f["contrast"])
    right = sorted([f for f in turns if f["human_steer"] > 0], key=lambda f: -f["contrast"])
    ex = []
    for i in range(args.n_curves):
        if i % 2 == 0 and right:
            ex.append(right.pop(0))
        elif left:
            ex.append(left.pop(0))
        elif right:
            ex.append(right.pop(0))

    fig, (axA, axB, axC) = plt.subplots(1, 3, figsize=(15.5, 4.6))

    # ---- (A) bold normalised E(steer) curves ----
    for f in ex:
        E = np.asarray(f["E"], float)
        en = (E - E.min()) / (E.max() - E.min() + 1e-12)
        tea = f["human_steer"]
        col = "#d62728" if tea < 0 else "#1f77b4"
        axA.plot(grid, en, "-", color=col, lw=2.6, alpha=0.85)
        axA.plot(grid[int(np.argmin(en))], 0.0, "o", color=col, ms=11, mec="k", mew=0.8)
        axA.axvline(tea, color=col, ls=":", lw=1.6, alpha=0.7)
    axA.axvline(0, color="grey", lw=0.7)
    axA.set_xlabel("swept steering  (−1 = left … +1 = right)", fontsize=10)
    axA.set_ylabel("normalized energy  E = ‖P̂ − z_goal‖₁", fontsize=10)
    axA.set_title("(A) Energy valley (●=argmin) sits on the human's turn side (dot)\n"
                  "red = human turned left · blue = right", fontsize=9.5)

    # ---- (B) scatter model vs human ----
    teas = np.asarray([f["human_steer"] for f in turns])
    bests = np.asarray([f["model_steer"] for f in turns])
    same = np.sign(teas) == np.sign(bests)
    axB.fill([0, 1, 1, 0], [0, 0, 1, 1], color="#2ca02c", alpha=0.06)
    axB.fill([0, -1, -1, 0], [0, 0, -1, -1], color="#2ca02c", alpha=0.06)
    axB.scatter(teas[same], bests[same], c="#2ca02c", s=26, edgecolor="k", linewidth=0.3, label="same sign")
    axB.scatter(teas[~same], bests[~same], c="#d62728", s=34, marker="x", label="diff sign")
    axB.plot([-1, 1], [-1, 1], color="grey", ls="--", lw=0.8)
    axB.axhline(0, color="grey", lw=0.6); axB.axvline(0, color="grey", lw=0.6)
    axB.set_xlim(-1.1, 1.1); axB.set_ylim(-1.1, 1.1); axB.set_aspect("equal")
    axB.set_xlabel("human steering (teacher)", fontsize=10)
    axB.set_ylabel("argmin-E (model's choice)", fontsize=10)
    axB.set_title(f"(B) Model vs human on {len(turns)} turn frames\n"
                  f"sign-correct {s['sign_correct_turn']}/{s['sign_total_turn']} = "
                  f"{100*s['sign_acc_turn']:.0f}%", fontsize=9.5)
    axB.legend(fontsize=8, loc="lower right")

    # ---- (C) full-session time × steer heatmap ----
    # Show the PREFERENCE (low energy = bright valley), faded by contrast so near-flat
    # straight-driving frames stay dark instead of amplifying noise. Bright ridge = the
    # steer the model prefers; it appears at turns and tracks the human.
    M = np.zeros((len(grid), len(frames)))
    hs, ms = [], []
    for j, f in enumerate(frames):
        if not f.get("E"):
            continue
        E = np.asarray(f["E"], float)
        pref = (E.max() - E) / (E.max() - E.min() + 1e-12)        # valley(low E)=1 bright
        w = min(f.get("contrast", 0.0) / 0.5, 1.0)                # fade flat frames
        M[:, j] = pref * w
        hs.append((j, f["human_steer"])); ms.append((j, f["model_steer"]))
    im = axC.imshow(M, aspect="auto", origin="lower", cmap="magma",
                    extent=[0, len(frames), grid.min(), grid.max()], vmin=0, vmax=1)
    hj, hv = zip(*hs); mj, mv = zip(*ms)
    axC.plot(hj, hv, color="#39ff14", lw=1.2, alpha=0.85, label="human")
    axC.set_xlabel("frame (time →)", fontsize=10)
    axC.set_ylabel("steering", fontsize=10)
    axC.set_title("(C) Whole session: 'bright ridge' = model-preferred steer (bold at turns) tracks the human",
                  fontsize=9.5)
    axC.legend(fontsize=8, loc="upper right", framealpha=0.85)
    fig.colorbar(im, ax=axC, fraction=0.046, pad=0.02, label="preference (bright=low E) × contrast")

    fig.suptitle(f"Steering energy landscape — session {sess} (VAL held-out), goal ~{lead}s ahead, "
                 f"throttle = teacher · median contrast {s['median_contrast']}", fontsize=10.5, y=1.02)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print("wrote", args.out, "| curves:", len(ex), "| turn frames:", len(turns))


if __name__ == "__main__":
    main()
