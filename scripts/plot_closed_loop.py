#!/usr/bin/env python3
"""Parse a closed-loop inference log (logs/infer_*.log) and render report figures.

Produces, from the per-tick `[infer]` lines:
  1. cos-dropout figure  : centered-cos + |raw steer| vs tick (the failure signature)
  2. trajectory figure   : GPS xy path coloured by cos (bám tuyến rồi bung)

No GPU / no data/latents needed — pure log parsing. Re-run on any infer log:
    python scripts/plot_closed_loop.py logs/infer_20260613_171912.log --out docs/report/figures
"""
import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# [infer] seq340 manual 7/59 →la10 cos0.080 d=1.8m steer-0.34(raw-0.56) throt+0.06 (ga model +0.000) xy(-47.5,-19.2) (...)
LINE = re.compile(
    r"seq(?P<seq>\d+)\s+\w+\s+(?P<sg>\d+)/(?P<ntot>\d+).*?"
    r"cos(?P<cos>-?\d+\.\d+)\s+d=(?P<d>-?\d+\.\d+)m\s+"
    r"steer(?P<steer>[+-]\d+\.\d+)\(raw(?P<raw>[+-]\d+\.\d+)\)\s+"
    r"throt(?P<throt>[+-]\d+\.\d+).*?xy\((?P<x>-?\d+\.\d+),(?P<y>-?\d+\.\d+)\)"
)


def parse(log_path: Path):
    rows = []
    for ln in log_path.read_text(errors="ignore").splitlines():
        if "[infer]" not in ln:
            continue
        m = LINE.search(ln)
        if not m:
            continue
        g = m.groupdict()
        rows.append(
            dict(
                seq=int(g["seq"]), sg=int(g["sg"]), ntot=int(g["ntot"]),
                cos=float(g["cos"]), d=float(g["d"]),
                steer=float(g["steer"]), raw=float(g["raw"]),
                throt=float(g["throt"]), x=float(g["x"]), y=float(g["y"]),
            )
        )
    return rows


def load_teach_xy(route_name: str):
    """Best-effort: load teach subgoal xy for an overlay (optional)."""
    meta = Path("data/routes/manual") / route_name / "meta.json"
    if not meta.exists():
        return None
    try:
        d = json.loads(meta.read_text())
        sg = d.get("subgoals") or d.get("nodes") or []
        xy = [(s.get("x"), s.get("y")) for s in sg if s.get("x") is not None]
        return np.array(xy) if xy else None
    except Exception:
        return None


def fig_dropout(rows, title, out):
    t = np.arange(len(rows))
    cos = np.array([r["cos"] for r in rows])
    raw = np.array([abs(r["raw"]) for r in rows])
    sg = np.array([r["sg"] for r in rows])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True,
                                   gridspec_kw=dict(height_ratios=[1.25, 1]))
    THR = 0.1
    # shade the cos-dropout zone (cos < threshold)
    drop = cos < THR
    ax1.fill_between(t, -1, 1, where=drop, color="#d62728", alpha=0.10, step="mid",
                     label="cos-dropout zone (cos < 0.1)")
    ax1.plot(t, cos, "-o", color="#1f77b4", ms=4, lw=1.6, label="centered-cos (live vs teach subgoal)")
    ax1.axhline(THR, color="#d62728", ls="--", lw=1, alpha=0.8)
    ax1.axhline(0, color="grey", ls=":", lw=0.8)
    ax1.set_ylabel("centered-cos")
    ax1.set_ylim(min(-0.3, cos.min() - 0.05), max(0.45, cos.max() + 0.05))
    ax1.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax1.set_title(title, fontsize=11)

    ax2.fill_between(t, 0, 1.05, where=drop, color="#d62728", alpha=0.10, step="mid")
    ax2.plot(t, raw, "-o", color="#ff7f0e", ms=4, lw=1.6, label="|raw steer| (CEM output)")
    ax2.axhline(1.0, color="grey", ls=":", lw=0.8)
    ax2.set_ylabel("|raw steer|")
    ax2.set_xlabel("tick (each ≈ 1.8 s)")
    ax2.set_ylim(0, 1.08)
    ax2.legend(loc="upper left", fontsize=8, framealpha=0.9)

    # subgoal-transition markers + labels
    for i in range(1, len(sg)):
        if sg[i] != sg[i - 1]:
            for ax in (ax1, ax2):
                ax.axvline(i - 0.5, color="grey", lw=0.6, alpha=0.5)
            ax1.text(i - 0.5, ax1.get_ylim()[1], f"sg{sg[i]}", fontsize=7,
                     color="grey", ha="center", va="bottom")
    ax1.text(0.5, ax1.get_ylim()[1], f"sg{sg[0]}", fontsize=7, color="grey",
             ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print("wrote", out)


def fig_traj(rows, title, route_name, out):
    x = np.array([r["x"] for r in rows])
    y = np.array([r["y"] for r in rows])
    cos = np.array([r["cos"] for r in rows])

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    teach = load_teach_xy(route_name)
    if teach is not None and len(teach) > 1:
        ax.plot(teach[:, 0], teach[:, 1], "-", color="#2ca02c", lw=2.4, alpha=0.55,
                label="teach route (subgoals)", zorder=1)
    sc = ax.scatter(x, y, c=cos, cmap="RdYlBu", vmin=-0.2, vmax=0.35, s=45,
                    edgecolor="k", linewidth=0.4, zorder=3)
    ax.plot(x, y, "-", color="grey", lw=0.8, alpha=0.6, zorder=2)
    ax.scatter([x[0]], [y[0]], marker="o", s=120, facecolor="none",
               edgecolor="green", linewidth=2, label="start", zorder=4)
    ax.scatter([x[-1]], [y[-1]], marker="X", s=120, color="#d62728",
               label="veer off → STOP", zorder=4)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("centered-cos")
    ax.set_xlabel("x (m, graph frame)")
    ax.set_ylabel("y (m, graph frame)")
    ax.set_title(title, fontsize=11)
    ax.legend(loc="best", fontsize=8)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--out", type=Path, default=Path("docs/report/figures"))
    ap.add_argument("--route", default=None, help="route name for teach overlay (auto from log if omitted)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows = parse(args.log)
    if not rows:
        raise SystemExit(f"no [infer] rows parsed from {args.log}")
    print(f"parsed {len(rows)} ticks from {args.log.name}; "
          f"cos {min(r['cos'] for r in rows):.3f}..{max(r['cos'] for r in rows):.3f}, "
          f"subgoals {rows[0]['sg']}..{rows[-1]['sg']}/{rows[0]['ntot']}")

    # route name: from log header `route '<name>'` if not given
    route = args.route
    if route is None:
        m = re.search(r"route '([^']+)'", args.log.read_text(errors="ignore"))
        route = m.group(1) if m else ""

    stem = args.log.stem.replace("infer_", "")
    fig_dropout(rows, f"Closed-loop run {stem}: cos-dropout → lost gradient → full-lock",
                args.out / f"fig_cos_dropout_{stem}.png")
    fig_traj(rows, f"Run {stem} trajectory: tracks then veers off (color = cos)",
             route, args.out / f"fig_trajectory_{stem}.png")


if __name__ == "__main__":
    main()
