#!/usr/bin/env python3
"""H3: does the policy give a CONSISTENT action when the goal latent comes from a DIFFERENT
session at the same physical place? = the real deploy condition (teach route is a different pass
than the live run). Uses pooled latents + GPS (small files), towerpro (deploy domain) only.

For each anchor frame i in session A: in-session goal = pool_A[i+d]; cross-session goal = the
nearest frame from session B≠A at the same xy (≤--tol-m) with similar heading (≤--tol-deg). We
compare policy(z_A[i], goal_in) vs policy(z_A[i], goal_cross). High agreement (small |Δsteer|,
high sign-match) ⇒ control is robust to teach-from-another-pass; large divergence ⇒ the
cross-session representation shift (lighting/heading) propagates into the action = a deploy risk.
Compares baseline vs recovery policy.

    PYTHONPATH=src python scripts/eval_policy_xsession.py
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, "scripts")
from jepa_wm.data.state import load_state
from jepa_wm.models.policy_prior import load_policy
from jepa_wm.nav.graph import _read_gps
from train_policy_prior import load_split_and_roots


def session_frames(raw_dir, pooled_dir, s, cols, lat0, lon0, hd_base_m=1.5):
    """Return per-frame (latent, xy, heading, state) aligned to actions_synced rows."""
    pf = Path(pooled_dir) / f"{s}.pt"
    if not pf.exists():
        return None
    pool = torch.load(pf, weights_only=False)["latents"].float()
    # frame times
    with open(Path(raw_dir) / s / "actions_synced.csv") as f:
        tms = np.array([float(r["t_scene_ms"]) for r in csv.DictReader(f)])
    if len(tms) != pool.shape[0]:
        return None
    gt, gla, glo, _ = _read_gps(Path(raw_dir) / s / "gps.csv")
    if len(gt) < 5:
        return None
    order = np.argsort(gt); gt, gla, glo = gt[order], gla[order], glo[order]
    lat = np.interp(tms, gt, gla); lon = np.interp(tms, gt, glo)
    mlon = 111320.0 * math.cos(math.radians(lat0)); mlat = 110540.0
    x = (lon - lon0) * mlon; y = (lat - lat0) * mlat
    # heading from xy track over ~hd_base_m baseline; valid only where moving enough
    n = len(x); hd = np.full(n, np.nan)
    for i in range(n):
        j = i
        while j + 1 < n and math.hypot(x[j] - x[i], y[j] - y[i]) < hd_base_m:
            j += 1
        if j > i and math.hypot(x[j] - x[i], y[j] - y[i]) >= hd_base_m * 0.6:
            hd[i] = math.atan2(y[j] - y[i], x[j] - x[i])
    st, fidx = load_state(Path(raw_dir) / s, cols)
    if len(fidx) != n:
        return None
    return pool, x, y, hd, torch.from_numpy(st).float()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wm", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("--baseline", default="checkpoints/policy_prior_cd4/best.pt")
    ap.add_argument("--recovery", default="checkpoints/policy_recovery_cd4_a06/best.pt")
    ap.add_argument("--goal-d", type=int, default=2)
    ap.add_argument("--tol-m", type=float, default=1.0)
    ap.add_argument("--tol-deg", type=float, default=40.0)
    ap.add_argument("--n", type=int, default=4000)
    args = ap.parse_args()

    ckpt = torch.load(args.wm, map_location="cpu", weights_only=False)
    cfg, roots, sessions = load_split_and_roots(ckpt)
    d_ = cfg["data"]; cols = tuple(d_["state_columns"]); stride = d_.get("frame_stride", 2)
    sm, ss = ckpt["state_mean"].float(), ckpt["state_std"].float()
    use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)
    tp = next(r for r in roots if "towerpro" in r["raw_dir"])           # deploy domain
    dom = float(tp.get("domain_id", 1)); raw, pooled = tp["raw_dir"], tp["pooled_dir"]

    # common origin
    g0 = _read_gps(Path(raw) / tp["_sessions"][0] / "gps.csv")
    lat0, lon0 = float(np.median(g0[1])), float(np.median(g0[2]))

    POOL, X, Y, HD, ST, SIDX = [], [], [], [], [], []
    for si, s in enumerate(tp["_sessions"]):
        r = session_frames(raw, pooled, s, cols, lat0, lon0)
        if r is None:
            continue
        pool, x, y, hd, st = r
        POOL.append(pool); X.append(x); Y.append(y); HD.append(hd); ST.append(st)
        SIDX.append(np.full(len(x), si))
    POOL = torch.cat(POOL); X = np.concatenate(X); Y = np.concatenate(Y)
    HD = np.concatenate(HD); ST = torch.cat(ST); SIDX = np.concatenate(SIDX)
    # per-session frame offsets for goal-d indexing
    sess_len = {si: int((SIDX == si).sum()) for si in np.unique(SIDX)}
    sess_start = {}; acc = 0
    for si in sorted(sess_len): sess_start[si] = acc; acc += sess_len[si]
    valid = np.isfinite(HD) & np.isfinite(X)
    vidx = np.where(valid)[0]
    XY = np.stack([X, Y], 1)
    from scipy.spatial import cKDTree
    tree = cKDTree(XY[vidx])
    print(f"[xsess] {len(np.unique(SIDX))} towerpro sess, {len(X)} frames, {valid.sum()} valid(moving) "
          f"| goal-d {args.goal_d} tol {args.tol_m}m/{args.tol_deg}° | origin ({lat0:.5f},{lon0:.5f})")

    # sample anchors that have an in-session goal d ahead within same session
    rng = np.random.default_rng(0)
    cand = []
    for si in sorted(sess_len):
        st0 = sess_start[si]; L = sess_len[si]
        for loc in range(L - args.goal_d * stride):
            gi = st0 + loc + args.goal_d * stride
            if valid[st0 + loc] and valid[gi]:
                cand.append((st0 + loc, gi, si))
    if not cand:
        print("no candidates"); return
    sel = [cand[t] for t in rng.choice(len(cand), min(args.n * 3, len(cand)), replace=False)]

    # build cross-session matches
    A_cur, G_in, G_cross, A_st, A_dom = [], [], [], [], []
    for (ai, gi, si) in sel:
        if len(A_cur) >= args.n:
            break
        gx, gy, ghd = X[gi], Y[gi], HD[gi]
        nbrs = tree.query_ball_point([gx, gy], args.tol_m)
        best = None
        for nb in nbrs:
            fi = vidx[nb]
            if SIDX[fi] == si:           # need a DIFFERENT session
                continue
            dh = abs(math.atan2(math.sin(HD[fi] - ghd), math.cos(HD[fi] - ghd)))
            if math.degrees(dh) > args.tol_deg:
                continue
            dd = math.hypot(X[fi] - gx, Y[fi] - gy)
            if best is None or dd < best[1]:
                best = (fi, dd)
        if best is None:
            continue
        A_cur.append(POOL[ai]); G_in.append(POOL[gi]); G_cross.append(POOL[best[0]])
        A_st.append(ST[ai]); A_dom.append(dom)
    if len(A_cur) < 30:
        print(f"chỉ {len(A_cur)} match cross-session (quá ít) — nới --tol-m/--tol-deg"); return
    A_cur = torch.stack(A_cur); G_in = torch.stack(G_in); G_cross = torch.stack(G_cross)
    A_st = torch.stack(A_st); A_dom = torch.tensor(A_dom)
    A_st = (A_st - sm) / ss
    print(f"[xsess] {len(A_cur)} anchor có match cross-session\n")

    for name, path in [("baseline", args.baseline), ("recovery", args.recovery)]:
        if not Path(path).exists():
            print(f"  [{name}] {path} MISSING"); continue
        model, _ = load_policy(path, device="cpu")
        perm = np.random.default_rng(1).permutation(len(A_cur))   # control: goal LẠ (random)
        with torch.no_grad():
            a_in = model(A_cur, G_in, A_st, A_dom if use_domain else None).numpy()
            a_cr = model(A_cur, G_cross, A_st, A_dom if use_domain else None).numpy()
            a_rd = model(A_cur, G_in[perm], A_st, A_dom if use_domain else None).numpy()
        ds = np.abs(a_in[:, 0] - a_cr[:, 0]); dr = np.abs(a_in[:, 0] - a_rd[:, 0])
        sign = np.mean(np.sign(a_in[:, 0]) == np.sign(a_cr[:, 0]))
        corr = np.corrcoef(a_in[:, 0], a_cr[:, 0])[0, 1]
        print(f"── {name} ── cross-session goal: med|Δsteer| {np.median(ds):.3f} sign {100*sign:.0f}% corr {corr:.2f}"
              f"  ||  control goal-LẠ: med|Δsteer| {np.median(dr):.3f} corr {np.corrcoef(a_in[:,0],a_rd[:,0])[0,1]:.2f}")
    print("\nĐọc: nếu Δ(cross) << Δ(goal-lạ) → policy NHẠY goal NHƯNG bền cross-session (tốt nhất cho deploy).")
    print("     nếu Δ(cross) ≈ Δ(goal-lạ) ≈ 0 → policy ÍT nhạy goal = reactive theo current-view (vẫn ok teach&repeat:")
    print("     bám hành-lang + recovery theo current-view; nhưng localize chọn ĐÚNG chỗ quan trọng hơn goal-fidelity).")


if __name__ == "__main__":
    main()
