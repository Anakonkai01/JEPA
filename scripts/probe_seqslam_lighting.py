"""Probe: localization CROSS-LIGHTING — sequence-matching (SeqSLAM) vs single-frame.

Bài toán (06-14, "vấn đề cosine"): teach-and-repeat POP/localize dùng centered-pooled
cosine 1-frame → SẬP khi ánh sáng đổi (nắng→mây). `probe_route_sim.py --cross-sessions`
đã đo: MỌI phép-đo-1-frame (ccos/−top1PC/patch-L1) localize ±1 ≈ random 15% cross-lighting.
CHƯA đo: **sequence-matching** (SeqSLAM) — fix chuẩn literature cho condition-invariance
(local-contrast-norm triệt tiêu "cả route dịch cùng nhau khi đổi sáng").

Script này (thuần numpy/CPU, dùng LATENT ĐÃ ENCODE — không re-encode GPU):
  1. Tự tìm CẶP session chồng-không-gian (ref=teach, query=khác-buổi) có lệch thời gian
     lớn (proxy lệch sáng) + cùng chiều đi.
  2. Build difference matrix D[query_i, ref_j] từ descriptor (centered-cos pooled,
     tuỳ chọn patch-L1) → local-contrast-norm → sequence search (velocity-constrained
     diagonal) ở các chiều-dài chuỗi Ls ∈ {1,5,10,20} (Ls=1 = single-frame baseline).
  3. CHẤM bằng HÌNH HỌC: localize-error = ||query_xy[i] − ref_xy[matched_j]||. In median
     error (m) + %<tol per method×Ls → CỔNG QUYẾT (SeqSLAM kéo %<tol từ ~15% lên >60%?).

Chạy:
  PYTHONPATH=src python scripts/probe_seqslam_lighting.py --auto-pairs 3
  PYTHONPATH=src python scripts/probe_seqslam_lighting.py --auto-pairs 3 --with-patch
  PYTHONPATH=src python scripts/probe_seqslam_lighting.py --pairs sessA,sessB sessC,sessD
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

try:
    import cv2
except ImportError:
    cv2 = None

_MLAT = 110540.0


def _m_per_deg_lon(lat0: float) -> float:
    return 111320.0 * math.cos(math.radians(lat0))


# ----------------------------------------------------------------------------- IO
def read_gps(path: Path):
    """(t_ms, lat, lon) dropping null fixes — như graph._read_gps."""
    t, la, lo = [], [], []
    if not path.exists():
        return np.array([]), np.array([]), np.array([])
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                a, b = float(r["lat"]), float(r["lon"])
                if a == 0 or b == 0:
                    continue
                t.append(float(r["t_ms"])); la.append(a); lo.append(b)
            except (ValueError, KeyError):
                continue
    return np.array(t), np.array(la), np.array(lo)


def read_synced_t(path: Path):
    """frame_idx (N,), t_scene_ms (N,) theo đúng thứ tự hàng (align với latent)."""
    fi, ts = [], []
    with open(path) as f:
        for r in csv.DictReader(f):
            fi.append(int(r["frame_idx"])); ts.append(float(r["t_scene_ms"]))
    return np.asarray(fi, np.int64), np.asarray(ts, np.float64)


def session_dt(name: str):
    """session_YYYYMMDD_HHMMSS → datetime (None nếu không parse được)."""
    try:
        return datetime.strptime(name.replace("session_", ""), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


class Sess:
    """Một session đã nạp: pooled latent + xy + heading per-frame (align latent row)."""

    def __init__(self, name, pool, xy, head, spd, fidx, raw_dir):
        self.name, self.pool, self.xy = name, pool, xy
        self.head, self.spd, self.fidx, self.raw_dir = head, spd, fidx, raw_dir


def load_session(name, latents_dir, raw_dir, origin, head_baseline=1.2):
    """Nạp pooled latent + nội suy xy/heading từ GPS (origin chung để xy so được)."""
    lp = Path(latents_dir) / f"{name}.pt"
    sdir = Path(raw_dir) / name
    if not lp.exists() or not (sdir / "gps.csv").exists():
        return None
    blob = torch.load(lp, map_location="cpu", weights_only=False)
    pool = blob["latents"].numpy().astype(np.float32)          # (N,1024) align actions_synced
    fidx, ts = read_synced_t(sdir / "actions_synced.csv")
    n = min(len(pool), len(ts))
    pool, ts, fidx = pool[:n], ts[:n], fidx[:n]
    gt, gla, glo = read_gps(sdir / "gps.csv")
    if len(gt) < 3:
        return None
    lat0, lon0 = origin
    gx = (glo - lon0) * _m_per_deg_lon(lat0)
    gy = (gla - lat0) * _MLAT
    x = np.interp(ts, gt, gx); y = np.interp(ts, gt, gy)
    xy = np.stack([x, y], 1).astype(np.float32)
    # heading trên baseline ~1.2m (đỡ nhiễu GPS — như inference_loop man_head)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
    head = np.zeros(n, np.float32); spd = np.zeros(n, np.float32)
    for k in range(n):
        i0 = i1 = k
        while i0 > 0 and cum[k] - cum[i0] < head_baseline / 2:
            i0 -= 1
        while i1 < n - 1 and cum[i1] - cum[k] < head_baseline / 2:
            i1 += 1
        dx, dy = xy[i1] - xy[i0]
        head[k] = math.atan2(dy, dx) if (dx or dy) else (head[k - 1] if k else 0.0)
    dt = np.gradient(ts) / 1000.0
    seg = np.concatenate([[0.0], np.linalg.norm(np.diff(xy, axis=0), axis=1)])
    spd = seg / np.clip(dt, 0.02, None)
    return Sess(name, pool, xy, head, spd.astype(np.float32), fidx, sdir)


# --------------------------------------------------------------------- pair finding
def all_session_names(latents_dir, raw_dir):
    out = []
    for lp in sorted(Path(latents_dir).glob("session_*.pt")):
        if (Path(raw_dir) / lp.stem / "gps.csv").exists():
            out.append(lp.stem)
    return out


def global_origin(names, raw_dir):
    las, los = [], []
    for nm in names:
        gt, gla, glo = read_gps(Path(raw_dir) / nm / "gps.csv")
        if len(gt):
            las.append(float(np.median(gla))); los.append(float(np.median(glo)))
    return (float(np.mean(las)), float(np.mean(los)))


def find_pairs(names, latents_dir, raw_dir, origin, *, n_pairs, overlap_r,
               min_overlap, min_gap_min, min_frames, sub=4):
    """Trả list (ref, query, info) — chồng-không-gian, cùng chiều, lệch thời gian lớn nhất."""
    tracks, dts = {}, {}
    for nm in names:
        s = load_session(nm, latents_dir, raw_dir, origin)
        if s is None or len(s.xy) < min_frames:
            continue
        mov = s.spd > 0.25                          # chỉ đoạn xe lăn
        if mov.sum() < min_frames:
            continue
        tracks[nm] = (s.xy[::sub], s.head[::sub], s.xy[mov], s.head[mov])
        dts[nm] = session_dt(nm)
    keys = [k for k in tracks if dts[k] is not None]
    cand = []
    for i in range(len(keys)):
        for j in range(len(keys)):
            if i == j:
                continue
            a, b = keys[i], keys[j]                 # a=ref, b=query
            gap = abs((dts[a] - dts[b]).total_seconds()) / 60.0
            if gap < min_gap_min:
                continue
            qxy, qhd = tracks[b][2], tracks[b][3]
            rxy, rhd = tracks[a][2], tracks[a][3]
            # bbox prefilter
            if (qxy[:, 0].min() > rxy[:, 0].max() or qxy[:, 0].max() < rxy[:, 0].min()
                    or qxy[:, 1].min() > rxy[:, 1].max() or qxy[:, 1].max() < rxy[:, 1].min()):
                continue
            # overlap fraction: query points có ref point trong overlap_r
            d = np.linalg.norm(qxy[:, None, :] - rxy[None, :, :], axis=2)  # (Nq,Nr)
            nn = d.min(1); on = nn < overlap_r
            frac = float(on.mean())
            if frac < min_overlap:
                continue
            # cùng chiều: heading-diff trung vị ở vùng chồng
            jbest = d[on].argmin(1)
            hdiff = np.abs((qhd[on] - rhd[jbest] + np.pi) % (2 * np.pi) - np.pi)
            if np.median(hdiff) > math.radians(70):     # anti-parallel → bỏ
                continue
            cand.append((gap * frac, gap, frac, a, b))
    cand.sort(reverse=True)
    seen, out = set(), []
    for score, gap, frac, a, b in cand:
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        out.append((a, b, dict(gap_min=gap, overlap=frac)))
        if len(out) >= n_pairs:
            break
    return out


# ------------------------------------------------------------------- descriptors
def centered_cos(ref_pool, qry_pool):
    """D[i,j] = 1 − cos(query_i, ref_j), centered theo MEAN của REF (= route mean ở inference)."""
    c = ref_pool.mean(0)
    R = ref_pool - c; Q = qry_pool - c
    Rn = R / (np.linalg.norm(R, axis=1, keepdims=True) + 1e-8)
    Qn = Q / (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-8)
    return (1.0 - Qn @ Rn.T).astype(np.float32)


def patch_l1(ref_tok, qry_tok):
    """D[i,j] = mean|qtok_i − rtok_j| (token đã LN). ref_tok/qry_tok: (N,T,D) fp32 LN'd."""
    Nq = len(qry_tok)
    D = np.empty((Nq, len(ref_tok)), np.float32)
    for i in range(Nq):
        D[i] = np.abs(ref_tok - qry_tok[i]).mean(axis=(1, 2))
    return D


def load_patch_ln(name, patch_dir, rows):
    """Patch tokens cho các hàng `rows`, layer-norm per-token (như ACClipDataset)."""
    arr = np.load(Path(patch_dir) / f"{name}.npy", mmap_mode="r")
    z = torch.from_numpy(np.ascontiguousarray(arr[rows])).float()
    z = torch.nn.functional.layer_norm(z, (z.size(-1),))
    return z.numpy().astype(np.float32)


# ------------------------------------------------------------------ SeqSLAM core
def contrast_norm(D, win):
    """Local contrast normalization dọc trục REF (cột) per query-row: triệt 'offset chung'."""
    Nq, Nr = D.shape
    if win <= 0 or win >= Nr:
        m = D.mean(1, keepdims=True); s = D.std(1, keepdims=True)
        return (D - m) / (s + 1e-6)
    k = np.ones(win, np.float32) / win
    out = np.empty_like(D)
    for i in range(Nq):
        row = D[i]
        m = np.convolve(row, k, mode="same")
        m2 = np.convolve(row * row, k, mode="same")
        s = np.sqrt(np.maximum(m2 - m * m, 1e-8))
        out[i] = (row - m) / (s + 1e-6)
    return out


def seq_match(D, Ls, vels):
    """Trả matched_ref_idx (Nq,) — diagonal sequence search velocity-constrained.
    D nhỏ=khớp. Ls=1 → single-frame argmin. matched[i] = ref endpoint của chuỗi tốt nhất."""
    Nq, Nr = D.shape
    INF = np.float32(1e9)
    best = np.full((Nq, Nr), INF, np.float32)
    for v in vels:
        acc = np.zeros((Nq, Nr), np.float32)
        ok = np.ones((Nq, Nr), bool)
        for k in range(Ls):
            c = int(round(k * v))
            sh = np.full((Nq, Nr), INF, np.float32)
            if k < Nq and c < Nr:
                sh[k:, c:] = D[:Nq - k, :Nr - c]
            acc += sh
            ok &= sh < INF
        acc[~ok] = INF
        np.minimum(best, acc, out=best)
    matched = best.argmin(1)
    matched[best.min(1) >= INF] = -1
    return matched


# ----------------------------------------------------------------------- evaluate
def eval_pair(ref, qry, *, patch_dir, tol_m, on_path_m, seq_lens, vels, win, with_patch):
    """In bảng method×Ls cho 1 cặp. Trả dict kết quả gộp."""
    print(f"\n=== ref={ref.name}  query={qry.name} "
          f"(Nref={len(ref.pool)} Nqry={len(qry.pool)}) ===")
    # frame query HỢP LỆ = đang trên đường ref + xe lăn
    dxy = np.linalg.norm(qry.xy[:, None, :] - ref.xy[None, :, :], axis=2)   # (Nq,Nr)
    nn_ref = dxy.argmin(1); nn_d = dxy.min(1)
    valid = (nn_d < on_path_m) & (qry.spd > 0.25)
    nval = int(valid.sum())
    if nval < 20:
        print(f"  [bỏ] chỉ {nval} frame query trên-đường — quá ít")
        return None
    # geo-error nếu chọn ĐÚNG ref gần nhất (sàn dưới của phương pháp hoàn hảo)
    floor = nn_d[valid]
    print(f"  on-path query: {nval} frame | geo-floor (ref gần nhất) median {np.median(floor):.2f}m "
          f"%<{tol_m}m {100*(floor<tol_m).mean():.0f}%")
    # CHẨN ĐOÁN ref: dài đường + đa-vòng (revisit) — SeqSLAM giả định CO-TRAVERSAL 1-pass,
    # ref đa-vòng/bao phủ rộng hơn query sẽ phá diagonal velocity search.
    rlen = float(np.linalg.norm(np.diff(ref.xy, axis=0), axis=1).sum())
    rd = np.linalg.norm(ref.xy[:, None, :] - ref.xy[None, :, :], axis=2)
    revisit = float(np.median((rd < 1.0).sum(1)))     # # ref frame trong 1m của mỗi frame
    # với mỗi query on-path: có BAO NHIÊU ref frame ở trong tol (alias vị-trí)?
    alias = float(np.median((dxy[valid] < tol_m).sum(1)))
    print(f"  ref path {rlen:.0f}m, {len(ref.pool)} frame | revisit(≤1m) median {revisit:.0f} "
          f"(>~3 = đa-vòng) | alias vị-trí/query median {alias:.0f} ref-frame trong {tol_m}m")

    results = {}

    def score(matched, label):
        m = matched[valid]
        good = m >= 0
        err = np.full(nval, np.nan, np.float32)
        err[good] = np.linalg.norm(qry.xy[valid][good] - ref.xy[m[good]], axis=1)
        e = err[good]
        med = float(np.median(e)) if len(e) else float("nan")
        pct = 100.0 * float((e < tol_m).mean()) if len(e) else 0.0
        # monotonic (không nhảy-lùi) trên frame hợp lệ liên tiếp
        seq = m[good]
        mono = 100.0 * float(np.mean(np.diff(seq) >= -2)) if len(seq) > 1 else 0.0
        print(f"    {label:<22} median {med:5.2f}m   %<{tol_m}m {pct:5.1f}   "
              f"monotonic {mono:4.0f}%   (matched {good.sum()}/{nval})")
        results[label] = dict(median_m=med, pct=pct, mono=mono)

    # ---- centered-cos base ----
    Dc = centered_cos(ref.pool, qry.pool)
    # ★ CHẨN ĐOÁN QUYẾT ĐỊNH: ref ĐÚNG-HÌNH-HỌC (trong tol) đứng HẠNG MẤY theo cosine?
    # rank thấp (≤5) → descriptor đúng gần top, chuỗi/SeqSLAM CÓ cửa cứu. rank cao (≫) →
    # appearance sai hẳn → KHÔNG temporal-trick nào cứu, phải đổi DESCRIPTOR (learned head).
    ranks = []
    for qi in np.where(valid)[0]:
        true_j = np.where(dxy[qi] < tol_m)[0]
        if len(true_j) == 0:
            continue
        order = np.argsort(Dc[qi])                      # ref theo cosine gần→xa
        rank_of = {int(j): r for r, j in enumerate(order)}
        ranks.append(min(rank_of[int(j)] for j in true_j))  # hạng TỐT NHẤT của ref-đúng
    if ranks:
        ranks = np.asarray(ranks)
        print(f"  ★ rank ref-đúng (cosine): median {np.median(ranks):.0f}/{len(ref.pool)} | "
              f"%top1 {100*(ranks==0).mean():.0f} %top5 {100*(ranks<5).mean():.0f} "
              f"%top20 {100*(ranks<20).mean():.0f}")
    # single-frame THÔ (đúng inference: argmax cos = argmin D, KHÔNG contrast-norm)
    score(Dc.argmin(1), "ccos 1-frame(raw)")
    # seq-on-RAW (cô lập: chuỗi cộng dồn D thô, KHÔNG contrast-norm) — xem chuỗi có giúp
    # khi xuất phát từ raw cos (vốn đã khá) không.
    for Ls in seq_lens:
        if Ls > 1:
            score(seq_match(Dc, Ls, vels), f"ccos seq-RAW Ls={Ls}")
    # seq-on-CONTRAST-NORM (SeqSLAM chuẩn) — local-contrast-norm rồi mới chuỗi.
    Dn = contrast_norm(Dc, win)
    for Ls in seq_lens:
        if Ls > 1:
            score(seq_match(Dn, Ls, vels), f"ccos seq-NORM Ls={Ls}")

    # ---- patch-L1 base (tuỳ chọn, nặng → subsample) ----
    if with_patch and patch_dir:
        rr = np.arange(len(ref.pool)); qr = np.arange(len(qry.pool))
        rtok = load_patch_ln(ref.name, patch_dir, rr)
        qtok = load_patch_ln(qry.name, patch_dir, qr)
        Dp = patch_l1(rtok, qtok)
        score(Dp.argmin(1), "patchL1 1-frame")
        Dpn = contrast_norm(Dp, win)
        for Ls in seq_lens:
            score(seq_match(Dpn, Ls, vels if Ls > 1 else [1.0]),
                  f"patchL1 SeqSLAM Ls={Ls}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latents-dir", default="data/latents_towerpro")
    ap.add_argument("--patch-dir", default="data/latents_towerpro_patch_384")
    ap.add_argument("--raw-dir", default="data/raw_towerpro")
    ap.add_argument("--auto-pairs", type=int, default=3, help="tự tìm N cặp cross-lighting")
    ap.add_argument("--pairs", nargs="*", default=None,
                    help="thủ công: 'ref,query' (bỏ qua auto)")
    ap.add_argument("--tol-m", type=float, default=1.5, help="localize đúng nếu err < tol")
    ap.add_argument("--on-path-m", type=float, default=3.0, help="query coi như trên-đường ref")
    ap.add_argument("--overlap-r", type=float, default=3.0)
    ap.add_argument("--min-overlap", type=float, default=0.5)
    ap.add_argument("--min-gap-min", type=float, default=30.0, help="lệch thời gian tối thiểu (phút)")
    ap.add_argument("--min-frames", type=int, default=60)
    ap.add_argument("--seq-lens", type=int, nargs="*", default=[1, 5, 10, 20])
    ap.add_argument("--vels", type=float, nargs="*", default=[0.8, 0.9, 1.0, 1.1, 1.2])
    ap.add_argument("--contrast-window", type=int, default=15)
    ap.add_argument("--with-patch", action="store_true", help="thêm base patch-L1 (nặng)")
    ap.add_argument("--multiref", type=int, default=0,
                    help=">0: thí nghiệm MULTI-REFERENCE — query so với BANK K session "
                         "(đa-sáng) thay vì 1 ref. Đo rank ref-đúng có tụt về top không.")
    args = ap.parse_args()

    names = all_session_names(args.latents_dir, args.raw_dir)
    print(f"[probe] {len(names)} session có latent+gps")
    origin = global_origin(names, args.raw_dir)
    print(f"[probe] origin (lat0,lon0) = {origin}")

    if args.pairs:
        pairs = []
        for p in args.pairs:
            a, b = p.split(",")
            pairs.append((a, b, {}))
    else:
        pairs = find_pairs(names, args.latents_dir, args.raw_dir, origin,
                           n_pairs=args.auto_pairs, overlap_r=args.overlap_r,
                           min_overlap=args.min_overlap, min_gap_min=args.min_gap_min,
                           min_frames=args.min_frames)
        print(f"[probe] tìm được {len(pairs)} cặp cross-lighting:")
        for a, b, info in pairs:
            print(f"    {a}  ×  {b}  (Δt {info['gap_min']:.0f}', overlap {info['overlap']:.0%})")

    agg = {}
    for a, b, info in pairs:
        ref = load_session(a, args.latents_dir, args.raw_dir, origin)
        qry = load_session(b, args.latents_dir, args.raw_dir, origin)
        if ref is None or qry is None:
            print(f"  [bỏ] không nạp được {a} / {b}")
            continue
        if cv2 is not None:                       # đo Δsáng (proxy thật) trên cặp đã chọn
            db = _bright_delta(ref, qry)
            if db is not None:
                print(f"  Δbrightness(ref,query) ≈ {db:+.1f}/255")
        res = eval_pair(ref, qry, patch_dir=args.patch_dir, tol_m=args.tol_m,
                        on_path_m=args.on_path_m, seq_lens=args.seq_lens,
                        vels=args.vels, win=args.contrast_window, with_patch=args.with_patch)
        if res:
            for k, v in res.items():
                agg.setdefault(k, []).append(v["pct"])

    if agg:
        print(f"\n=== TỔNG ({len(pairs)} cặp) — %<{args.tol_m}m (median qua các cặp) ===")
        base = np.median(agg.get("ccos 1-frame(raw)", [float('nan')]))
        for k in sorted(agg):
            med = float(np.median(agg[k]))
            mark = " ★" if ("seq-" in k and med >= base + 10) else ""
            print(f"  {k:<22} {med:5.1f}%{mark}")
        print(f"\n[CỔNG] single-frame baseline = {base:.0f}%.  PASS nếu seq-* (Ls≥10) vượt "
              f"baseline +10đ (★) VÀ đạt ≥60%. FAIL → learned-head (ViNG) + re-teach-cùng-buổi.")

    # ----- MULTI-REFERENCE (deploy-able, rẻ): query vs BANK K session đa-sáng -----
    if args.multiref > 0 and pairs:
        qname = pairs[-1][1]                          # query đã FAIL ở single-ref
        query = load_session(qname, args.latents_dir, args.raw_dir, origin)
        banks, btimes = [], []
        for nm in names:                              # gom session overlap query path
            if nm == qname:
                continue
            s = load_session(nm, args.latents_dir, args.raw_dir, origin)
            if s is None or len(s.xy) < args.min_frames:
                continue
            d = np.linalg.norm(query.xy[:, None, :] - s.xy[None, :, :], axis=2)
            if (d.min(1) < args.overlap_r).mean() < args.min_overlap:
                continue
            dt = session_dt(nm)
            if dt is not None:
                banks.append(s); btimes.append(dt)
        if len(banks) >= 2:
            order_t = np.argsort(btimes)              # chọn K trải đều theo thời gian (đa-sáng)
            pick = order_t[np.linspace(0, len(order_t) - 1, min(args.multiref, len(order_t))).astype(int)]
            banks = [banks[i] for i in pick]
            print(f"\n=== MULTI-REFERENCE: query {qname} vs bank {len(banks)} session đa-sáng "
                  f"({btimes[pick[0]]:%m-%d %H:%M} … {btimes[pick[-1]]:%m-%d %H:%M}) ===")
            multiref_rank(query, banks, args.tol_m, args.on_path_m)
        else:
            print(f"\n[multiref] không đủ session overlap query {qname}")


def multiref_rank(query, banks, tol_m, on_path_m, gate_m=5.0):
    """Rank ref-đúng khi match query vs BANK gộp (nhiều session/ánh sáng). %top1 cao =
    có ref cùng-sáng trong bank → localize cứu được mà KHÔNG train (chỉ cần lưu nhiều ref).
    Đo CẢ 2: UNGATED (so toàn bank) và GPS-GATED (chỉ so ref trong gate_m — đúng deploy,
    pop/localize vốn đã gated GPS) → tách 'descriptor sai' khỏi 'distractor xa'."""
    BP = np.concatenate([b.pool for b in banks])
    BXY = np.concatenate([b.xy for b in banks])
    BS = np.concatenate([np.full(len(b.pool), i) for i, b in enumerate(banks)])
    dxy = np.linalg.norm(query.xy[:, None, :] - BXY[None, :, :], axis=2)
    valid = (dxy.min(1) < on_path_m) & (query.spd > 0.25)
    c = BP.mean(0)
    Bn = BP - c; Bn = Bn / (np.linalg.norm(Bn, axis=1, keepdims=True) + 1e-8)
    ru, rg, top1_sess = [], [], []
    for qi in np.where(valid)[0]:
        true = np.where(dxy[qi] < tol_m)[0]
        if len(true) == 0:
            continue
        q = query.pool[qi] - c; q = q / (np.linalg.norm(q) + 1e-8)
        sims = Bn @ q
        order = np.argsort(-sims)
        rank_of = {int(j): r for r, j in enumerate(order)}
        ru.append(min(rank_of[int(j)] for j in true))
        top1_sess.append(int(BS[order[0]]))
        gate = np.where(dxy[qi] < gate_m)[0]          # chỉ ref trong gate GPS
        if len(gate):
            go = gate[np.argsort(-sims[gate])]        # ref trong gate theo cosine
            gr = {int(j): r for r, j in enumerate(go)}
            tg = [j for j in true if j in gr]
            rg.append(min(gr[int(j)] for j in tg) if tg else len(go))
    if ru:
        ru = np.asarray(ru); rg = np.asarray(rg) if rg else None
        used = len(set(top1_sess))
        print(f"  bank {len(BP)} frame | UNGATED rank ref-đúng median {np.median(ru):.0f}/{len(BP)} "
              f"| %top1 {100*(ru==0).mean():.0f} %top5 {100*(ru<5).mean():.0f} "
              f"%top20 {100*(ru<20).mean():.0f} | top1 từ {used}/{len(banks)} session")
        if rg is not None:
            print(f"  GPS-GATED (≤{gate_m:g}m, đúng deploy): %top1 {100*(rg==0).mean():.0f} "
                  f"%top3 {100*(rg<3).mean():.0f}  (correct-ref là best-appearance trong gate?)")
            ok = (rg == 0).mean()
            print("  → GPS-GATED multi-ref CỨU localize KHÔNG cần train (chỉ lưu nhiều ref/chỗ)"
                  if ok > 0.5 else
                  "  → ngay cả GPS-gated %top1 thấp → descriptor SAI dưới đổi-sáng, cần LEARNED head")


def _bright_delta(ref, qry, k=6):
    def mean_b(s):
        idx = np.linspace(0, len(s.fidx) - 1, k).astype(int)
        vals = []
        for i in idx:
            fp = s.raw_dir / "frames" / f"{int(s.fidx[i]):06d}.jpg"
            im = cv2.imread(str(fp))
            if im is not None:
                vals.append(im.mean())
        return float(np.mean(vals)) if vals else None
    a, b = mean_b(ref), mean_b(qry)
    return None if (a is None or b is None) else (a - b)


if __name__ == "__main__":
    main()
