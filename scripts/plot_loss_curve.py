#!/usr/bin/env python3
"""Training loss curve for the report — NO GPU.

Plots the AC-predictor validation L1 loss (teacher-forcing + 2-step rollout objective)
per epoch for the deploy run, annotated with the WSD-style schedule:

  - base run: cosine LR (60-epoch budget), val drops 0.79 -> 0.60 by ep9 then plateaus
    (the cosine tail never arrives within the deadline; this is the WSD "stable" phase);
  - power cut interrupted the base run mid-ep12;
  - cooldown run (cd4): re-init from ep9 best.pt, LR ~0.5x peak -> 0 over 3 epochs (decay
    phase), pushing val from 0.60 down to ~0.584.

Numbers are read from the training log (docs/HANDOFF.md / wandb summaries); this script just
plots them so the figure is reproducible alongside the report.

    PYTHONPATH=src python scripts/plot_loss_curve.py --out docs/report/figures/fig_loss_curve.png
"""
from __future__ import annotations

import argparse

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# val L1 loss (tf + rollout) per epoch, base run ep0..9 (HANDOFF training log)
VAL_BASE = [0.7937, 0.6984, 0.6862, 0.6566, 0.6407, 0.6177, 0.6195, 0.6083, 0.6052, 0.6001]
# cooldown (cd4): init from ep9 best.pt, LR->0; deploy best.pt = cooldown ep2, val 0.5693
# (ep9 carry -> cd ep1 0.5760 -> cd ep2 0.5693; wandb group vjepa_ac_car_cd4 + checkpoint val)
VAL_COOLDOWN = [0.6001, 0.5760, 0.5693]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/report/figures/fig_loss_curve.png")
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    ep_base = np.arange(len(VAL_BASE))
    ax.plot(ep_base, VAL_BASE, "-o", color="#0275d8", lw=2.0, ms=5, label="base run · cosine LR (val L1)")

    # cooldown continues from ep9
    ep_cd = np.arange(len(VAL_BASE) - 1, len(VAL_BASE) - 1 + len(VAL_COOLDOWN))
    ax.plot(ep_cd, VAL_COOLDOWN, "-s", color="#d9534f", lw=2.0, ms=5,
            label="cooldown cd4 · LR→0 (decay)")

    # phase shading / annotations
    ax.axvspan(0, 6, color="#0275d8", alpha=0.05)
    ax.axvspan(6, 9, color="#5cb85c", alpha=0.06)
    ax.axvspan(9, ep_cd[-1], color="#d9534f", alpha=0.06)
    ax.annotate("WSD 'stable' plateau ~0.60\n(cosine tail không tới kịp deadline)",
                xy=(8, 0.605), xytext=(3.4, 0.66), fontsize=8.2,
                arrowprops=dict(arrowstyle="->", color="#5cb85c"))
    ax.annotate("cúp điện giữa ep12 →\nre-init ep9 best.pt, cooldown",
                xy=(9, 0.600), xytext=(4.6, 0.55), fontsize=8.2,
                arrowprops=dict(arrowstyle="->", color="#d9534f"))
    ax.annotate(f"deploy best.pt (cd4)\nval {VAL_COOLDOWN[-1]:.3f} · rollout@1/idn 0.744",
                xy=(ep_cd[-1], VAL_COOLDOWN[-1]), xytext=(ep_cd[-1] - 3.0, 0.625), fontsize=8.2,
                arrowprops=dict(arrowstyle="->", color="k"))

    ax.set_xlabel("epoch", fontsize=10)
    ax.set_ylabel("val L1 loss  (teacher-forcing + 2-step rollout)", fontsize=10)
    ax.set_ylim(0.54, 0.82)
    ax.set_title("Đường cong huấn luyện AC Predictor (val) — lịch LR kiểu WSD: base cosine "
                 "→ plateau → cooldown LR→0", fontsize=9.8)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="upper right")
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
