#!/usr/bin/env python3
"""Build the topological navigation graph from V-JEPA latents + GPS.

    # KDS only (latents already encoded):
    python scripts/build_graph.py --out data/graph/topograph_kds.pt

    # all 92 sessions (after encoding TowerPro):
    python scripts/build_graph.py \
        --root data/latents:data/raw:kds \
        --root data/latents_towerpro:data/raw_towerpro:towerpro \
        --out data/graph/topograph.pt

Each ``--root`` is ``LATENTS_DIR:RAW_DIR[:DOMAIN]``. Prints a connectivity +
place-recognition report and saves the graph.
"""
from __future__ import annotations

import argparse
import math

import numpy as np

from jepa_wm.nav import build_topograph


def parse_root(s: str) -> dict:
    parts = s.split(":")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("root must be LATENTS_DIR:RAW_DIR[:DOMAIN]")
    return {"latents": parts[0], "raw": parts[1], "domain": parts[2] if len(parts) > 2 else None}


def place_recognition_report(g, n=1500, seed=0):
    """Sanity: NN latent in a *different* session -> how far in GPS metres."""
    rng = np.random.default_rng(seed)
    M = len(g.Zn)
    q = rng.choice(M, size=min(n, M), replace=False)
    errs, rnd = [], []
    sims_all = g.Zn[q] @ g.Zn.T
    for k, i in enumerate(q):
        mask = g.suid != g.suid[i]
        s = sims_all[k].copy(); s[~mask] = -2
        j = int(np.argmax(s))
        errs.append(float(np.linalg.norm(g.XY[i] - g.XY[j])))
        jr = int(rng.choice(np.where(mask)[0]))
        rnd.append(float(np.linalg.norm(g.XY[i] - g.XY[jr])))
    errs = np.array(errs); rnd = np.array(rnd)
    return {
        "median_m": float(np.median(errs)), "p90_m": float(np.percentile(errs, 90)),
        "within_8m_pct": float(100 * np.mean(errs < 8)),
        "random_baseline_m": float(np.median(rnd)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=parse_root, action="append", default=None,
                    help="LATENTS_DIR:RAW_DIR[:DOMAIN]; repeatable")
    ap.add_argument("--out", default="data/graph/topograph_kds.pt")
    ap.add_argument("--node-stride", type=int, default=5)
    ap.add_argument("--knn", type=int, default=8)
    ap.add_argument("--gps-gate-m", type=float, default=8.0)
    ap.add_argument("--sim-min", type=float, default=0.5)
    args = ap.parse_args()

    roots = args.root or [{"latents": "data/latents", "raw": "data/raw", "domain": "kds"}]
    print(f"[build_graph] roots: {[(r['latents'], r['raw']) for r in roots]}")
    g = build_topograph(roots, node_stride=args.node_stride, knn=args.knn,
                        gps_gate_m=args.gps_gate_m, sim_min=args.sim_min)

    comps = g.components()
    M = len(g.Zn)
    pr = place_recognition_report(g)

    print("\n================= GRAPH REPORT =================")
    print(f"nodes:            {M}")
    print(f"temporal edges:   {g.params['n_temporal']}")
    print(f"loop edges:       {g.params['n_loop']}  (alias rejected by GPS: {g.params['n_alias_rejected']})")
    print(f"components:        {len(comps)}  | largest {len(comps[0])}/{M} ({100*len(comps[0])/M:.0f}%)")
    print(f"  top-5 sizes:     {[len(c) for c in comps[:5]]}")
    print(f"place-recognition (NN cross-session GPS error):")
    print(f"  median {pr['median_m']:.1f} m | p90 {pr['p90_m']:.1f} m | "
          f"<8m {pr['within_8m_pct']:.0f}% | random baseline {pr['random_baseline_m']:.1f} m")
    # area covered
    span_x = float(g.XY[:, 0].max() - g.XY[:, 0].min())
    span_y = float(g.XY[:, 1].max() - g.XY[:, 1].min())
    print(f"extent:           {span_x:.0f} m x {span_y:.0f} m")
    print("================================================\n")

    g.save(args.out)
    print(f"[build_graph] saved -> {args.out}")


if __name__ == "__main__":
    main()
