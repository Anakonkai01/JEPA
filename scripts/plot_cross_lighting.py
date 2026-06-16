#!/usr/bin/env python3
"""N2 — localization descriptor collapses under a lighting shift between teach and run.

The key Section 13.2 evidence, otherwise text-only. Bars = fraction of closed-loop ticks whose
pooled-latent cosine to the matching teach image exceeds 0.3 (the 'well localized' band), for two
real runs: teach & run in the same session a few minutes apart vs. teach & run under shifted sun.
Values are read from the real-run logs in logs/infer_20260613_*.log (Section 13.2).

    python scripts/plot_cross_lighting.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("docs/report/figures/fig_cross_lighting.png")

# fraction of ticks with cos > 0.3, from real closed-loop run logs (Section 13.2)
COND = ["Same session,\nnear in time", "Different lighting\n(teach 14:11, run 14:50)"]
PCT = [66, 0]
COLORS = ["#2e7d32", "#c62828"]


def main():
    fig, ax = plt.subplots(figsize=(7.0, 4.7))
    bars = ax.bar(COND, PCT, color=COLORS, width=0.55, edgecolor="black", linewidth=0.8, zorder=3)
    ax.axhline(0, color="black", linewidth=0.8)
    for b, p in zip(bars, PCT):
        ax.text(b.get_x() + b.get_width() / 2, p + 2.2, f"{p}%", ha="center", va="bottom",
                fontsize=16, fontweight="bold", color=b.get_facecolor())
    ax.set_ylabel("ticks with localization cosine > 0.3  (%)", fontsize=11)
    ax.set_ylim(0, 80)
    ax.set_title("Localization descriptor is NOT lighting-invariant\n"
                 "(pooled-latent cosine to teach image, per tick)",
                 fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.annotate("control stays robust\n(patch-L1 changes < 5%);\nonly the pooled-cosine\nlocator collapses",
                xy=(1, 0), xytext=(1.05, 34), fontsize=8.6, color="#444444", ha="center",
                bbox=dict(boxstyle="round,pad=0.35", fc="#fff8e1", ec="#f0ad4e", lw=0.8))
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
