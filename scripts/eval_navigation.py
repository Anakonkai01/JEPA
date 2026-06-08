#!/usr/bin/env python3
"""Offline evaluation of the topological navigation graph (no car, no phone).

    python scripts/eval_navigation.py --graph data/graph/topograph_kds.pt

Reports:
  1. Localization (leave-one-session-out): localize each frame using only OTHER
     sessions -> GPS error. This is the honest generalization of place-recognition.
  2. Routing: random cross-park (start, goal) pairs -> % routable, path/straight
     length ratio, #session-switches, #subgoals.
  3. Route-vs-actual: treat each session as a known A->B human drive; block it,
     localize its endpoints via the rest, plan a route, and measure how closely
     the planned corridor follows the real driven path (median deviation, metres).
"""
from __future__ import annotations

import argparse

import numpy as np

from jepa_wm.nav import TopoGraph


def path_metres(g, path):
    return float(sum(np.linalg.norm(g.XY[b] - g.XY[a]) for a, b in zip(path[:-1], path[1:])))


def corridor_dev(A, B):
    """Symmetric median point-to-polyline deviation (metres) between vertex sets."""
    d2 = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)
    return float(np.median(np.concatenate([d2.min(1), d2.min(0)])))


def eval_localization(g, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    M = len(g.Zn)
    q = rng.choice(M, size=min(n, M), replace=False)
    sims_all = g.Zn[q] @ g.Zn.T
    errs = []
    for k, i in enumerate(q):
        s = sims_all[k].copy()
        s[g.suid == g.suid[i]] = -2          # exclude same session (LOSO)
        j = int(np.argmax(s))
        errs.append(float(np.linalg.norm(g.XY[i] - g.XY[j])))
    errs = np.array(errs)
    return {"median_m": float(np.median(errs)), "p75_m": float(np.percentile(errs, 75)),
            "p90_m": float(np.percentile(errs, 90)), "within_8m_pct": float(100 * np.mean(errs < 8))}


def eval_routing(g, n=300, min_straight_m=20.0, spacing_m=4.0, seed=1):
    rng = np.random.default_rng(seed)
    M = len(g.Zn)
    ok = 0; tried = 0; ratios = []; switches = []; nsubs = []
    while tried < n:
        a, b = int(rng.integers(M)), int(rng.integers(M))
        straight = float(np.linalg.norm(g.XY[a] - g.XY[b]))
        if g.suid[a] == g.suid[b] or straight < min_straight_m:
            continue
        tried += 1
        route = g.plan_route(a, b)
        if route is None:
            continue
        ok += 1
        ratios.append(path_metres(g, route) / max(straight, 1e-6))
        switches.append(int(sum(g.suid[u] != g.suid[v] for u, v in zip(route[:-1], route[1:]))))
        nsubs.append(len(g.extract_subgoals(route, spacing_m)))
    return {"success_pct": float(100 * ok / max(tried, 1)),
            "median_length_ratio": float(np.median(ratios)) if ratios else float("nan"),
            "median_switches": float(np.median(switches)) if switches else float("nan"),
            "median_subgoals": float(np.median(nsubs)) if nsubs else float("nan"),
            "tried": tried, "routable": ok}


def eval_route_vs_actual(g, max_sessions=15, min_span_m=15.0, seed=2):
    rng = np.random.default_rng(seed)
    uids = np.unique(g.suid)
    rng.shuffle(uids)
    rows = []
    for u in uids:
        ids = np.where(g.suid == u)[0]          # in frame order
        if len(ids) < 10:
            continue
        a_node, b_node = int(ids[0]), int(ids[-1])
        span = float(np.linalg.norm(g.XY[a_node] - g.XY[b_node]))
        if span < min_span_m:
            continue
        blocked = set(ids.tolist())
        start = g.localize(g.Zn[a_node], blocked=blocked)
        goal = g.localize(g.Zn[b_node], blocked=blocked)
        route = g.plan_route(start, goal, blocked=blocked)
        if route is None:
            rows.append({"uid": int(u), "routable": False, "span_m": span})
            continue
        dev = corridor_dev(g.XY[ids], g.XY[np.array(route)])
        rows.append({"uid": int(u), "routable": True, "span_m": span,
                     "corridor_dev_m": dev,
                     "planned_m": path_metres(g, route),
                     "actual_m": path_metres(g, ids.tolist())})
        if len([r for r in rows if r.get("routable")]) >= max_sessions:
            break
    good = [r for r in rows if r.get("routable")]
    devs = np.array([r["corridor_dev_m"] for r in good]) if good else np.array([])
    return {"sessions_tested": len(rows), "routable": len(good),
            "median_corridor_dev_m": float(np.median(devs)) if len(devs) else float("nan"),
            "p90_corridor_dev_m": float(np.percentile(devs, 90)) if len(devs) else float("nan"),
            "rows": good}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="data/graph/topograph_kds.pt")
    ap.add_argument("--spacing-m", type=float, default=4.0)
    args = ap.parse_args()

    g = TopoGraph.load(args.graph)
    M = len(g.Zn)
    print(f"[eval_nav] graph {args.graph}: {M} nodes\n")

    loc = eval_localization(g)
    print("1) LOCALIZATION (leave-one-session-out):")
    print(f"   median {loc['median_m']:.1f} m | p75 {loc['p75_m']:.1f} | p90 {loc['p90_m']:.1f} "
          f"| <8m {loc['within_8m_pct']:.0f}%\n")

    rt = eval_routing(g, spacing_m=args.spacing_m)
    print("2) ROUTING (random cross-park pairs):")
    print(f"   routable {rt['success_pct']:.0f}% ({rt['routable']}/{rt['tried']}) | "
          f"length ratio {rt['median_length_ratio']:.2f}x | "
          f"switches {rt['median_switches']:.0f} | subgoals {rt['median_subgoals']:.0f}\n")

    rva = eval_route_vs_actual(g)
    print("3) ROUTE vs ACTUAL human A->B drive (held-out session):")
    print(f"   sessions {rva['routable']}/{rva['sessions_tested']} routable | "
          f"corridor deviation median {rva['median_corridor_dev_m']:.1f} m "
          f"(p90 {rva['p90_corridor_dev_m']:.1f} m)")
    print("   → small deviation = planned route follows a real drivable corridor.")


if __name__ == "__main__":
    main()
