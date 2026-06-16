#!/usr/bin/env python3
"""Dataset overview figure for the report (replaces the §7.1 table) — NO GPU.

Reads docs/report/figures/dataset_stats.json (written by dataset_stats.py) and draws three
small panels comparing the two servo domains: #sessions, #frames, hours. A compact visual
that's easier to read than the raw table.

    PYTHONPATH=src python scripts/plot_dataset_overview.py --out docs/report/figures/fig_data_overview.png
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
    ap.add_argument("--stats", default="docs/report/figures/dataset_stats.json")
    ap.add_argument("--out", default="docs/report/figures/fig_data_overview.png")
    args = ap.parse_args()

    d = json.load(open(args.stats))["per_domain"]
    kds, tp, alld = d["KDS"], d["TowerPro"], d["ALL"]

    labels = ["KDS\n(old servo)", "TowerPro\n(new servo)"]
    colors = ["#9b59b6", "#0275d8"]
    panels = [
        ("#sessions", [kds["sessions"], tp["sessions"]], alld["sessions"], "{:.0f}"),
        ("#frames", [kds["frames"], tp["frames"]], alld["frames"], "{:,.0f}"),
        ("Duration (hours)", [kds["hours"], tp["hours"]], alld["hours"], "{:.2f}h"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    for ax, (title, vals, total, fmt) in zip(axes, panels):
        xs = np.arange(len(vals))
        ax.bar(xs, vals, color=colors, width=0.6, zorder=3)
        for x, v in zip(xs, vals):
            ax.text(x, v, fmt.format(v), ha="center", va="bottom", fontsize=10, fontweight="bold")
        ax.set_xticks(xs); ax.set_xticklabels(labels, fontsize=9)
        ax.set_title(f"{title}  ·  TOTAL {fmt.format(total)}", fontsize=10)
        ax.margins(y=0.18)
        ax.grid(axis="y", alpha=0.2)

    fig.suptitle(f"Dataset: {alld['sessions']} sessions · {alld['frames']:,} frames · "
                 f"{alld['hours']:.2f} hours of real driving (saved FPS ~{alld['avg_fps']:.1f}) · session split 80/20 → 167 train / 42 val",
                 fontsize=10.5, y=1.04)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
