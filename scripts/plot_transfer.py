#!/usr/bin/env python3
"""Cross-domain-servo transfer figure for the report — NO GPU.

Two panels:
  (A) rollout@1 / identity on the SAME held-out TowerPro sessions, as a 3-step progression:
      TowerPro ALONE (1.073, worse than the no-change baseline) -> pretrain on the old KDS
      servo then finetune on TowerPro (0.975, barely beats it) -> train on the MIX KDS+TowerPro
      at once (0.65, best). The 1.0 line is the no-change ("standstill") baseline (<1 = beats it).
  (B) the mixed model's validation L1 loss over training epochs (converges ~0.60).

Numbers are read from the training run (logged in docs/HANDOFF.md); this script just plots
them so the figure is reproducible alongside the report.

    PYTHONPATH=src python scripts/plot_transfer.py --out docs/report/figures/fig_transfer.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# rollout@1 / identity on held-out TowerPro (lower = better; 1.0 = no-change baseline)
# Source: runs/lewm_overnight/20260608_015058/report.md
TOWERPRO_ONLY = 1.073      # train TowerPro only                 -> eval TowerPro held-out
FINETUNE      = 0.975      # pretrain KDS, then finetune TowerPro -> eval TowerPro held-out
MIXED = 0.65               # train KDS+TowerPro at once           -> eval TowerPro held-out
# mixed-model validation L1 loss (tf + rollout) per epoch (HANDOFF training log)
VAL_CURVE = [0.7937, 0.6984, 0.6862, 0.6566, 0.6407, 0.6177, 0.6195, 0.6083, 0.6052, 0.6001]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/report/figures/fig_transfer.png")
    args = ap.parse_args()

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.2))

    # ---- (A) 3-step progression ----
    bars = [("Chỉ TowerPro\n(servo mới)", TOWERPRO_ONLY, "#d9534f"),
            ("Pretrain KDS →\nfinetune TowerPro", FINETUNE, "#f0ad4e"),
            ("Train trộn\nKDS + TowerPro", MIXED, "#0275d8")]
    xs = np.arange(len(bars))
    axA.bar(xs, [b[1] for b in bars], color=[b[2] for b in bars], width=0.6, zorder=3)
    axA.axhline(1.0, color="k", ls="--", lw=1.2, zorder=2)
    axA.text(2.45, 1.005, "baseline đứng-yên (=1.0)", ha="right", va="bottom", fontsize=8.5)
    for x, (lab, v, _) in zip(xs, bars):
        axA.text(x, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
        axA.text(x, 0.04, "THUA" if v >= 1.0 else "THẮNG", ha="center", va="bottom",
                 color="white", fontsize=9, fontweight="bold")
    axA.set_xticks(xs); axA.set_xticklabels([b[0] for b in bars], fontsize=8.5)
    axA.set_ylabel("rollout@1 / identity  (eval TowerPro held-out)", fontsize=9.5)
    axA.set_ylim(0, 1.2)
    axA.set_title("(A) Càng dùng nhiều dữ liệu servo-cũ càng tốt:\nchỉ-servo-mới THUA → finetune ≈ hoà → trộn THẮNG",
                  fontsize=9.5)

    # ---- (B) val curve over epochs ----
    ep = np.arange(len(VAL_CURVE))
    axB.plot(ep, VAL_CURVE, "-o", color="#0275d8", lw=2.0, ms=5)
    axB.set_xlabel("epoch", fontsize=9.5)
    axB.set_ylabel("val L1 loss (tf + rollout)", fontsize=9.5)
    axB.set_ylim(0.55, 0.85)
    axB.set_title("(B) Model trộn: val loss giảm đều 0.79 → 0.60\n(học động học chung, không overfit servo)",
                  fontsize=9.5)
    axB.grid(alpha=0.25)

    fig.suptitle("Transfer chéo-domain-servo: dữ liệu servo-khác giúp học động học chung "
                 "(domain_id phân biệt ánh xạ lệnh→góc)", fontsize=10, y=1.02)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
