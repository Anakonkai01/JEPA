#!/usr/bin/env python3
"""Visualize one planned navigation route on the park map + subgoal thumbnails.

    python scripts/viz_route.py --graph data/graph/topograph_kds.pt --out data/graph/route_viz.png

Picks a far-apart (start, goal) pair (or use --start/--goal node ids), plans the
route, extracts subgoal frames, and saves a PNG: park map with the route + a strip
of the subgoal images the local controller would chase. Open the PNG in VSCode.
"""
from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from jepa_wm.nav import TopoGraph


def pick_pair(g, min_straight_m, seed):
    rng = np.random.default_rng(seed)
    M = len(g.Zn)
    for _ in range(20000):
        a, b = int(rng.integers(M)), int(rng.integers(M))
        if g.suid[a] == g.suid[b]:
            continue
        if np.linalg.norm(g.XY[a] - g.XY[b]) >= min_straight_m and g.plan_route(a, b):
            return a, b
    raise SystemExit("No far-apart routable pair found.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="data/graph/topograph_kds.pt")
    ap.add_argument("--start", type=int, default=None)
    ap.add_argument("--goal", type=int, default=None)
    ap.add_argument("--min-straight-m", type=float, default=40.0)
    ap.add_argument("--spacing-m", type=float, default=6.0)
    ap.add_argument("--max-thumbs", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/graph/route_viz.png")
    args = ap.parse_args()

    g = TopoGraph.load(args.graph)
    if args.start is not None and args.goal is not None:
        a, b = args.start, args.goal
    else:
        a, b = pick_pair(g, args.min_straight_m, args.seed)

    route = g.plan_route(a, b)
    if route is None:
        raise SystemExit(f"No route {a} -> {b}")
    subs = g.extract_subgoals(route, spacing_m=args.spacing_m)
    rxy = g.XY[np.array(route)]
    straight = float(np.linalg.norm(g.XY[a] - g.XY[b]))
    length = float(sum(np.linalg.norm(rxy[i + 1] - rxy[i]) for i in range(len(rxy) - 1)))
    print(f"route {a}->{b}: {len(route)} nodes, {len(subs)} subgoals, "
          f"{length:.0f} m driven vs {straight:.0f} m straight ({length/straight:.2f}x)")

    # robust axis limits (ignore GPS-drift outliers)
    lo = np.percentile(g.XY, 1, axis=0); hi = np.percentile(g.XY, 99, axis=0)

    n_th = min(args.max_thumbs, len(subs))
    th_idx = np.linspace(0, len(subs) - 1, n_th).round().astype(int)
    fig = plt.figure(figsize=(13, 9))
    gs = fig.add_gridspec(3, n_th, height_ratios=[3, 0.15, 1.1])

    # --- map ---
    axm = fig.add_subplot(gs[0, :])
    axm.scatter(g.XY[:, 0], g.XY[:, 1], s=2, c="#cccccc", linewidths=0, label="park nodes")
    axm.plot(rxy[:, 0], rxy[:, 1], "-", c="#1f77b4", lw=2, label="planned route", zorder=3)
    sxy = g.XY[np.array(subs)]
    axm.scatter(sxy[:, 0], sxy[:, 1], s=40, c="#1f77b4", edgecolors="white", zorder=4, label="subgoals")
    axm.scatter(*g.XY[a], s=220, marker="*", c="#2ca02c", edgecolors="black", zorder=5, label="start")
    axm.scatter(*g.XY[b], s=220, marker="*", c="#d62728", edgecolors="black", zorder=5, label="goal")
    for k, s in enumerate(np.array(subs)[th_idx]):
        axm.annotate(str(k), g.XY[s], fontsize=8, color="black",
                     xytext=(3, 3), textcoords="offset points", zorder=6)
    axm.set_xlim(lo[0], hi[0]); axm.set_ylim(lo[1], hi[1]); axm.set_aspect("equal")
    axm.set_title(f"Planned route: {len(subs)} subgoals | {length:.0f} m vs {straight:.0f} m straight "
                  f"({length/straight:.2f}x)")
    axm.set_xlabel("east (m)"); axm.set_ylabel("north (m)"); axm.legend(loc="upper right", fontsize=8)

    # --- subgoal thumbnails ---
    for k, s in enumerate(np.array(subs)[th_idx]):
        ax = fig.add_subplot(gs[2, k])
        try:
            ax.imshow(Image.open(g.frame_path(int(s))).convert("RGB").resize((160, 90)))
        except Exception as e:
            ax.text(0.5, 0.5, "no img", ha="center", va="center"); print("img err:", e)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"#{k}" + (" start" if k == 0 else " goal" if k == n_th - 1 else ""), fontsize=8)

    fig.suptitle("Visual subgoal navigation — local CEM chases these images in order", fontsize=12)
    fig.savefig(args.out, dpi=110, bbox_inches="tight")
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
