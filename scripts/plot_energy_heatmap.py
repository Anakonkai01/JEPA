#!/usr/bin/env python3
"""N3 — one frame's joint energy landscape E(steer, throttle), with human vs model markers.

Makes the Tier-2 JOINT planner tangible: the 15x9 grid the planner actually scores for a single
real frame. Reads E2 (joint energy, 15 steer x 9 throttle) from a precomputed demo.json. Picks
the highest-contrast turning frame whose sign matches the human (clear single valley).

    python scripts/plot_energy_heatmap.py [--demo data/demo/<session>/demo.json] [--frame K]

No GPU: demo.json is precomputed.
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DEF_DEMO = "data/demo/session_20260608_173932/demo.json"
OUT = Path("docs/report/figures/fig_energy_heatmap.png")


def pick_frame(frames, want_k=None):
    by_k = {f["k"]: f for f in frames}
    if want_k is not None and want_k in by_k and by_k[want_k].get("E2") is not None:
        return by_k[want_k]
    best, best_c = None, -1
    for f in frames:
        if not f.get("is_turn") or f.get("E2") is None or not f.get("sign_ok"):
            continue
        c = f.get("contrast", 0)
        if c > best_c:
            best_c, best = c, f
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default=DEF_DEMO)
    ap.add_argument("--frame", type=int, default=None)
    args = ap.parse_args()

    d = json.load(open(args.demo))
    steer = np.array(d["grid"])        # 15 steering points
    thr = np.array(d["grid_thr"])      # 9 throttle points
    f = pick_frame(d["frames"], args.frame)
    if f is None:
        raise SystemExit("no suitable turn frame with E2 found")
    E2 = np.array(f["E2"])             # (15 steer, 9 throttle)
    # imshow wants rows=y(throttle), cols=x(steer)
    Z = E2.T                           # (9 throttle, 15 steer)

    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    extent = [steer[0], steer[-1], thr[0], thr[-1]]
    im = ax.imshow(Z, origin="lower", aspect="auto", extent=extent, cmap="magma_r")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    cb.set_label("energy  E = ‖ẑ − z_goal‖₁   (lower = closer to goal)", fontsize=9.5)

    # contour of the valley
    XS, YT = np.meshgrid(steer, thr)
    ax.contour(XS, YT, Z, levels=6, colors="white", alpha=0.25, linewidths=0.7)

    hs, ht = f["human_steer"], f["human_throttle"]
    ms, mt = f["model_steer"], f["model_throttle"]
    ax.scatter([hs], [ht], s=320, marker="o", facecolors="none", edgecolors="#39ff14",
               linewidths=2.6, label=f"human  ({hs:+.2f}, {ht:+.2f})", zorder=5)
    ax.scatter([ms], [mt], s=300, marker="X", color="#00e5ff", edgecolors="black",
               linewidths=0.8, label=f"model argmin  ({ms:+.2f}, {mt:+.2f})", zorder=6)

    ax.set_xlabel("steering   (−1 = left   ·   +1 = right)", fontsize=11)
    ax.set_ylabel("throttle", fontsize=11)
    ax.set_title(f"Joint planner energy landscape — one VAL frame (k={f['k']})\n"
                 f"15 steer × 9 throttle grid scored by the AC predictor · contrast {f.get('contrast',0):.2f}",
                 fontsize=11.5, fontweight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, fontsize=9.3, frameon=False)
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    print(f"wrote {OUT}  (session={d['session']}, frame k={f['k']})")


if __name__ == "__main__":
    main()
