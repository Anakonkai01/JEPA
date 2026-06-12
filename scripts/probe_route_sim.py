"""Probe độ-tin-cậy phép đo "đã tới subgoal" trên một route tay (teach & repeat).

Trả lời 2 câu (06-12 tối, quan sát của user: "từ subgoal ~14 — ngay cua — ccos thấp,
qua cua rồi vẫn thấp, không cao như các subgoal đầu"):

1. CẤU TRÚC ROUTE (chỉ cần ảnh teach): subgoal nửa sau có "mờ nhạt" (gần tâm route,
   norm centered nhỏ) / giống nhau (aliasing) hơn nửa đầu không? → in per-subgoal
   ‖z_i − c‖, ccos với kề/xa, margin, + so sánh CÁC PHÉP ĐO: cos thô / centered /
   bỏ-top-PC / whiten-shrink / patch-L1 / seq-2.

2. KHÁC NGÀY/KHÁC SÁNG (--cross-sessions): lấy frame NGƯỜI LÁI cũ (data/raw_*) có GPS
   rơi đúng xy subgoal + heading khớp → "live frame khác ngày" → ccos teach-vs-khác-ngày
   tại đúng mốc (đo domain-shift ánh sáng — route teach tối qua chạy sáng mai còn khớp?).

Chạy (GPU ~1-2'):
  PYTHONPATH=src python scripts/probe_route_sim.py --route parkfix2
  PYTHONPATH=src python scripts/probe_route_sim.py --route parkfix2 --cross-sessions 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder

try:
    import cv2
except ImportError:
    cv2 = None

_MLAT = 110574.0


def _m_per_deg_lon(lat0):
    import math
    return 111320.0 * math.cos(math.radians(lat0))


def encode_pool_tokens(enc, device, img_bgr, size=384):
    import PIL.Image as Image
    rgb = img_bgr[:, :, ::-1].copy()
    img = Image.fromarray(rgb).resize((size, size), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
    x = (x - IMAGENET_MEAN) / IMAGENET_STD
    x = x.unsqueeze(0).unsqueeze(2).to(device)
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16,
                                         enabled=device.startswith("cuda")):
        tok = enc(x)
    tok = tok.float()[0]                      # (576,1024)
    return tok.mean(0).cpu().numpy(), F.layer_norm(tok, (tok.size(-1),)).cpu().numpy()


def rankdata(a):
    order = np.argsort(a)
    r = np.empty(len(a), float)
    r[order] = np.arange(len(a), dtype=float)
    return r


def spearman(a, b):
    ra, rb = rankdata(np.asarray(a, float)), rankdata(np.asarray(b, float))
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def sim_metrics(S, name, far=3):
    """S (N,N) similarity (lớn = giống). In: NN-adjacent acc, margin kề-vs-xa, alias count,
    monotonicity (Spearman sim ↓ theo |Δidx|)."""
    N = S.shape[0]
    nn_ok, margins, alias_pairs, monos = 0, [], 0, []
    for i in range(N):
        row = S[i].copy(); row[i] = -np.inf
        j = int(np.argmax(row))
        if abs(j - i) == 1:
            nn_ok += 1
        adj = max(S[i, i - 1] if i > 0 else -np.inf, S[i, i + 1] if i + 1 < N else -np.inf)
        faridx = [j for j in range(N) if abs(j - i) >= far]
        fmax = max(S[i, j] for j in faridx) if faridx else -np.inf
        margins.append(adj - fmax)
        if fmax >= adj:
            alias_pairs += 1
        d = [-abs(j - i) for j in range(N) if j != i]
        s = [S[i, j] for j in range(N) if j != i]
        monos.append(spearman(s, d))
    print(f"  {name:<14} NN-kề {nn_ok}/{N}   margin(kề−xa≥{far}) median {np.median(margins):+.3f} "
          f"min {np.min(margins):+.3f}   alias-row {alias_pairs}/{N}   mono ρ median {np.median(monos):.2f}")
    return margins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="parkfix2", help="tên dưới data/routes/manual/")
    ap.add_argument("--routes-dir", default="data/routes")
    ap.add_argument("--cross-sessions", type=int, default=0,
                    help=">0: lấy tối đa N frame khác-ngày/subgoal từ data/raw_towerpro (GPS khớp xy)")
    ap.add_argument("--raw-dir", default="data/raw_towerpro")
    ap.add_argument("--xy-tol", type=float, default=1.2, help="m: frame cách subgoal dưới ngần này")
    ap.add_argument("--head-tol-deg", type=float, default=50.0)
    ap.add_argument("--graph", default="data/graph/topograph.pt", help="lấy origin lat/lon → xy frame")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    rdir = Path(args.routes_dir) / "manual" / args.route
    meta = json.loads((rdir / "meta.json").read_text())
    print(f"[probe] route {args.route}: {len(meta)} subgoal")
    enc = load_encoder(args.device)

    pools, toks, XY = [], [], []
    for sg in meta:
        img = cv2.imread(str(Path(args.routes_dir) / sg["img"]))
        assert img is not None, sg["img"]
        p, t = encode_pool_tokens(enc, args.device, img)
        pools.append(p); toks.append(t)
        XY.append(sg.get("xy") or [np.nan, np.nan])
    Z = np.stack(pools); T = np.stack(toks); XY = np.asarray(XY, np.float32)
    N = len(Z)

    # ---- hình học route (từ xy teach) ----
    seg = np.linalg.norm(np.diff(XY, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    hd = np.zeros(N)
    for k in range(N):
        a = XY[max(0, k - 1)]; b = XY[min(N - 1, k + 1)]
        hd[k] = np.arctan2(b[1] - a[1], b[0] - a[0])
    dh = np.degrees(np.abs((np.diff(hd) + np.pi) % (2 * np.pi) - np.pi))
    print(f"[geo] dài {cum[-1]:.1f}m, spacing median {np.median(seg):.2f}m (min {seg.min():.2f} max {seg.max():.2f})")
    print(f"[geo] |Δheading|/subgoal: median {np.median(dh):.0f}° p90 {np.percentile(dh, 90):.0f}° "
          f"— top-5 chỗ xoay mạnh: " + ", ".join(
              f"sg{i+1}→{i+2}:{dh[i]:.0f}°" for i in np.argsort(dh)[-5:][::-1]))

    # ---- centered cosine (đúng inference) ----
    c = Z.mean(0)
    V = Z - c
    nrm = np.linalg.norm(V, axis=1)
    Vn = V / (nrm[:, None] + 1e-8)
    C = Vn @ Vn.T
    print("\n[ccos] per-subgoal (norm-từ-tâm = độ 'đặc trưng'; ccos kề; max ccos tới sg xa ≥3):")
    half = np.median(nrm)
    for i in range(N):
        adj = max(C[i, i - 1] if i > 0 else -1, C[i, i + 1] if i + 1 < N else -1)
        faridx = [j for j in range(N) if abs(j - i) >= 3]
        fj = max(faridx, key=lambda j: C[i, j])
        flag = " ◄ MỜ" if nrm[i] < 0.75 * half else ""
        print(f"  sg{i+1:>2} ‖z−c‖ {nrm[i]:7.2f}{flag}  ccos kề {adj:+.3f}  xa-max {C[i, fj]:+.3f} (sg{fj+1})")

    # ---- so sánh phép đo ----
    print("\n[methods] so sánh trên ảnh teach (NN phải là subgoal kề; margin to + alias 0 = pop tin được):")
    Zr = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-8)
    sim_metrics(Zr @ Zr.T, "cos thô")
    sim_metrics(C, "centered")
    # bỏ top-PC (loại "thành phần chung" mạnh nhất — ánh sáng/cảnh chung)
    U, S, _ = np.linalg.svd(V, full_matrices=False)

    def drop_pc(k):
        Wk = (V.T @ U[:, :k]) / (S[:k] + 1e-8)      # right singular vecs (D,k), trực giao
        P = V - (V @ Wk) @ Wk.T
        Pn = P / (np.linalg.norm(P, axis=1, keepdims=True) + 1e-8)
        return Pn @ Pn.T
    sim_metrics(drop_pc(1), "ccos −top1PC")
    sim_metrics(drop_pc(2), "ccos −top2PC")
    # whiten-shrink trong subspace route: toạ độ PC = U·S → chia sqrt(S²+λ)
    lam = 0.1 * float(np.mean(S ** 2))
    A = U * S                                        # (N,N') toạ độ mỗi subgoal theo PC
    Aw = A / np.sqrt(S ** 2 + lam)
    Awn = Aw / (np.linalg.norm(Aw, axis=1, keepdims=True) + 1e-8)
    sim_metrics(Awn @ Awn.T, "whiten-shrink")
    # patch-token L1 (CEM energy, LN'd): sim = −L1
    L1 = np.zeros((N, N))
    for i in range(N):
        L1[i] = np.abs(T - T[i]).mean(axis=(1, 2))
    sim_metrics(-L1, "patch-L1")
    # seq-2 (khớp cặp ảnh liên tiếp — SeqSLAM mini)
    C2 = C.copy()
    for i in range(N - 1):
        for j in range(N - 1):
            C2[i, j] = (C[i, j] + C[i + 1, j + 1]) / 2
    sim_metrics(C2, "ccos seq-2")

    # ---- cross-session: frame khác ngày tại đúng xy subgoal ----
    if args.cross_sessions > 0:
        from jepa_wm.nav.graph import TopoGraph
        g = TopoGraph.load(args.graph)
        lat0, lon0 = g.origin
        cand = {i: [] for i in range(N)}
        for sdir in sorted(Path(args.raw_dir).glob("session_*")):
            gps = sdir / "gps.csv"; acts = sdir / "actions_synced.csv"
            if not gps.exists() or not acts.exists():
                continue
            garr = np.genfromtxt(gps, delimiter=",", names=True)
            if garr.size < 5:
                continue
            gx = (garr["lon"] - lon0) * _m_per_deg_lon(lat0)
            gy = (garr["lat"] - lat0) * _MLAT
            gt = garr["t_ms"]
            aarr = np.genfromtxt(acts, delimiter=",", names=True)
            ft = aarr["t_scene_ms"]; fidx = aarr["frame_idx"].astype(int)
            fx = np.interp(ft, gt, gx); fy = np.interp(ft, gt, gy)
            hx = np.interp(ft + 700, gt, gx) - np.interp(ft - 700, gt, gx)
            hy = np.interp(ft + 700, gt, gy) - np.interp(ft - 700, gt, gy)
            fhd = np.arctan2(hy, hx)
            spd = np.hypot(hx, hy) / 1.4
            for i in range(N):
                d = np.hypot(fx - XY[i, 0], fy - XY[i, 1])
                dhd = np.degrees(np.abs((fhd - hd[i] + np.pi) % (2 * np.pi) - np.pi))
                ok = np.where((d < args.xy_tol) & (dhd < args.head_tol_deg) & (spd > 0.3))[0]
                if len(ok):
                    b = ok[np.argmin(d[ok])]
                    cand[i].append((float(d[b]), sdir.name, int(fidx[b])))
        print(f"\n[cross] frame khác-ngày khớp xy+heading (tol {args.xy_tol}m/{args.head_tol_deg:.0f}°):")
        enc_cache = {}
        # phương pháp đánh giá dưới domain-shift: với mỗi frame khác-ngày, xem subgoal NÀO
        # giống nó nhất theo từng phép đo → đúng nếu argmax ∈ {i-1,i,i+1}. Phép đo sống sót
        # qua đổi-sáng = còn dùng được để pop khi route teach khác giờ.
        Wk1 = (V.T @ U[:, :1]) / (S[:1] + 1e-8)
        P1 = V - (V @ Wk1) @ Wk1.T
        P1n = P1 / (np.linalg.norm(P1, axis=1, keepdims=True) + 1e-8)
        hits = {"ccos": 0, "-top1PC": 0, "patchL1": 0}
        vals = {"ccos": [], "-top1PC": []}
        n_frames = 0
        for i in range(N):
            picks = sorted(cand[i])[: args.cross_sessions]
            if not picks:
                print(f"  sg{i+1:>2}: (không có frame nào đi ngang đúng chỗ+hướng)")
                continue
            ccs = []
            for d, sname, fi in picks:
                key = (sname, fi)
                if key not in enc_cache:
                    fp = Path(args.raw_dir) / sname / "frames" / f"{fi:06d}.jpg"
                    img = cv2.imread(str(fp))
                    if img is None:
                        continue
                    enc_cache[key] = encode_pool_tokens(enc, args.device, img)
                pool_f, tok_f = enc_cache[key]
                v = pool_f - c
                vn = v / (np.linalg.norm(v) + 1e-8)
                sims = Vn @ vn                                  # ccos tới mọi subgoal
                ccs.append((float(sims[i]), d, sname))
                n_frames += 1
                if abs(int(np.argmax(sims)) - i) <= 1:
                    hits["ccos"] += 1
                vals["ccos"].append(float(sims[i]))
                p = v - float(v @ Wk1[:, 0]) * Wk1[:, 0]         # bỏ top-1 PC của route
                pn = p / (np.linalg.norm(p) + 1e-8)
                sims1 = P1n @ pn
                if abs(int(np.argmax(sims1)) - i) <= 1:
                    hits["-top1PC"] += 1
                vals["-top1PC"].append(float(sims1[i]))
                l1 = np.abs(T - tok_f).mean(axis=(1, 2))
                if abs(int(np.argmin(l1)) - i) <= 1:
                    hits["patchL1"] += 1
            if ccs:
                s = " | ".join(f"ccos {cc:+.3f} (d {d:.1f}m, {sn[-6:]})" for cc, d, sn in ccs)
                pop = "✓pop@0.5" if max(cc for cc, _, _ in ccs) >= 0.5 else "✗<0.5"
                print(f"  sg{i+1:>2}: {s}  {pop}")
        if n_frames:
            print(f"\n[cross-methods] localize-trong-route đúng (±1) trên {n_frames} frame khác-ngày:")
            for k in ("ccos", "-top1PC", "patchL1"):
                print(f"  {k:<8} {hits[k]}/{n_frames} ({100 * hits[k] / n_frames:.0f}%)")
            for k in ("ccos", "-top1PC"):
                print(f"  giá trị tại subgoal đúng ({k}): median {np.median(vals[k]):+.3f} "
                      f"p90 {np.percentile(vals[k], 90):+.3f} max {np.max(vals[k]):+.3f}")


if __name__ == "__main__":
    main()
