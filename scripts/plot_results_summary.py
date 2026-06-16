#!/usr/bin/env python3
"""N1 — three-tier results scorecard (the 'whole story in 5 seconds').

Pure matplotlib, no data/GPU: numbers are the verified report figures (see report Appendix
"Reference figures"). Renders one card per evaluation tier with its verdict and headline metrics.

    python scripts/plot_results_summary.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path("docs/report/figures/fig_results_summary.png")

GREEN = "#2e7d32"
GREEN_BG = "#eaf6ea"
RED = "#c62828"
RED_BG = "#fdecea"
INK = "#222222"

TIERS = [
    dict(
        tag="TIER 1", verdict="PASS", color=GREEN, bg=GREEN_BG,
        title="Dynamics — offline",
        question="Does the predictor learn action → latent change?",
        lines=[
            ("0.744", "rollout@1 / identity", "< 1: beats the still-scene baseline"),
            ("0.703 / 0.697", "rollout@2 / @3", "better at every horizon"),
            ("1.073 → 0.65", "cross-servo transfer", "mixing both servos wins"),
        ],
    ),
    dict(
        tag="TIER 2", verdict="PASS", color=GREEN, bg=GREEN_BG,
        title="Planner — open-loop (joint steer+throttle)",
        question="Does the planner pick expert-like actions?",
        lines=[
            ("94.2%", "steering sign vs human", "841 / 893 turn frames"),
            ("0.118", "median |Δsteer|", "close in magnitude, scale [−1,1]"),
            ("91.9%", "throttle wants forward", "median |Δthrottle| = 0.033"),
        ],
    ),
    dict(
        tag="TIER 3", verdict="NOT YET", color=RED, bg=RED_BG,
        title="Closed-loop — outdoor",
        question="Can it actually drive the loop closed?",
        lines=[
            ("0 / 10", "runs reached the goal", "tracks first half, then veers off route", RED),
            ("✗", "localization descriptor", "pooled-cosine: not lighting/heading invariant", RED),
            ("✓", "world model itself is fine", "Tiers 1–2 confirm representation + planner", GREEN),
        ],
    ),
]


def card(ax, t):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    # background panel
    ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.01,rounding_size=0.03",
                                linewidth=2, edgecolor=t["color"], facecolor=t["bg"], mutation_aspect=1))
    # header band
    ax.add_patch(FancyBboxPatch((0.02, 0.82), 0.96, 0.16, boxstyle="round,pad=0.005,rounding_size=0.03",
                                linewidth=0, facecolor=t["color"]))
    ax.text(0.07, 0.895, t["tag"], color="white", fontsize=13, fontweight="bold", va="center")
    icon = "✓" if t["verdict"] == "PASS" else "✗"
    ax.text(0.93, 0.895, f"{icon} {t['verdict']}", color="white", fontsize=12.5,
            fontweight="bold", va="center", ha="right")
    # title + question
    ax.text(0.07, 0.75, t["title"], color=INK, fontsize=12.5, fontweight="bold", va="center")
    ax.text(0.07, 0.685, t["question"], color="#555555", fontsize=9.5, style="italic", va="center")
    # metric blocks (stacked): (value, label, note[, value_color])
    y = 0.64
    for row in t["lines"]:
        value, label, note = row[0], row[1], row[2]
        vcolor = row[3] if len(row) > 3 else t["color"]
        ax.text(0.075, y, value, color=vcolor, fontsize=17, fontweight="bold", va="center")
        ax.text(0.075, y - 0.058, label, color=INK, fontsize=9.7, fontweight="bold", va="center")
        ax.text(0.075, y - 0.097, note, color="#666666", fontsize=8.2, va="center")
        y -= 0.185


def main():
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    fig.suptitle("Results at a glance — frozen V-JEPA 2.1 world model for RC-car navigation",
                 fontsize=14.5, fontweight="bold", y=0.99)
    for ax, t in zip(axes, TIERS):
        card(ax, t)
    fig.text(0.5, 0.015,
             "Read left to right: the representation + planner work offline (Tiers 1-2); "
             "the gap that breaks closed-loop driving (Tier 3) is localization robustness, not the world model.",
             ha="center", fontsize=9.3, color="#444444")
    fig.subplots_adjust(left=0.012, right=0.988, top=0.9, bottom=0.075, wspace=0.06)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
