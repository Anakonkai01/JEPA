#!/usr/bin/env python3
"""Probe metric "đã tới subgoal chưa" trên 1 thư mục ảnh (route tay indoor).

Trả lời "cosine lúc nào cũng cao" TÁCH BẠCH khỏi closed-loop: encode mọi ảnh
trong --dir rồi in 3 ma trận cặp-đôi (ảnh i vs ảnh j):

  1. cos      — cosine pooled-latent THÔ (metric pop subgoal hiện tại trong
                inference_loop route tay). Park đo 06-12: 0.94–0.97 giữa các chỗ
                KHÁC nhau → saturate.
  2. ccos     — cosine sau khi TRỪ MEAN pooled của cả route (bỏ thành phần chung
                "đây là một cái ảnh trong nhà") — ứng viên thay thế rẻ nhất.
  3. L1tok    — mean |Δ| patch-token đã LN (= energy CEM ở horizon 0, eq.5 Meta,
                không qua world model) — kỳ vọng tách vị trí tốt nhất vì giữ cấu
                trúc không gian.

Đọc kết quả: metric tốt = đường chéo (i==j) TÁCH RÕ khỏi off-diagonal, và đơn
điệu dần theo |i-j| (ảnh chụp tuần tự dọc route). In kèm gap = (giá trị tệ nhất
cùng-chỗ) vs (tốt nhất khác-chỗ) cho từng metric.

    PYTHONPATH=src python scripts/probe_reach.py --dir data/routes/manual/test_nha
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder


@torch.no_grad()
def encode_dir(dir_: Path, device: str, size: int = 384):
    enc = load_encoder(device)
    paths = sorted(p for p in dir_.iterdir() if p.suffix.lower() in (".jpg", ".png", ".jpeg"))
    if not paths:
        raise SystemExit(f"no images in {dir_}")
    pools, toks = [], []
    for p in paths:
        img = Image.open(p).convert("RGB").resize((size, size), Image.BILINEAR)
        x = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
        x = ((x - IMAGENET_MEAN) / IMAGENET_STD).unsqueeze(0).unsqueeze(2).to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
            t = enc(x)
        t = t.float()[0]                                   # (576,1024)
        pools.append(t.mean(0).cpu())
        toks.append(F.layer_norm(t, (t.size(-1),)).cpu())
    return paths, torch.stack(pools), torch.stack(toks)


def show(name, M, names, lower_better=False):
    n = len(names)
    print(f"\n=== {name} ({'thấp=giống' if lower_better else 'cao=giống'}) ===")
    print("      " + " ".join(f"{Path(nm).stem:>6}" for nm in names))
    for i in range(n):
        print(f"{Path(names[i]).stem:>5} " + " ".join(f"{M[i, j]:6.3f}" for j in range(n)))
    # Ảnh chụp TUẦN TỰ dọc route → metric tốt phải đơn điệu theo |i-j| và
    # "giống nhất" (ngoài chính nó) phải là ảnh KỀ. Diag (i==j) tầm thường, bỏ.
    off = M.copy()
    np.fill_diagonal(off, np.inf if lower_better else -np.inf)
    nn = np.argmin(off, 1) if lower_better else np.argmax(off, 1)
    ok = sum(abs(int(nn[i]) - i) == 1 for i in range(n))
    by_d = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                by_d.setdefault(min(abs(i - j), 3), []).append(M[i, j])
    lvl = "  ".join(f"|Δ|={d if d < 3 else '3+'}: {np.mean(v):.3f}" for d, v in sorted(by_d.items()))
    print(f"  hàng-xóm-gần-nhất đúng là ảnh kề: {ok}/{n}  |  mean theo khoảng cách route → {lvl}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    paths, pools, toks = encode_dir(Path(args.dir), args.device)
    names = [p.name for p in paths]
    n = len(paths)

    pn = F.normalize(pools, dim=1)
    cos = (pn @ pn.T).numpy()

    c = pools - pools.mean(0, keepdim=True)
    cn = F.normalize(c, dim=1)
    ccos = (cn @ cn.T).numpy()

    l1 = np.zeros((n, n), np.float32)
    for i in range(n):
        l1[i] = (toks - toks[i]).abs().mean(dim=(1, 2)).numpy()

    print(f"[probe_reach] {args.dir}: {n} ảnh (theo thứ tự chụp dọc route)")
    show("1. cos pooled THÔ (metric pop hiện tại)", cos, names)
    show("2. ccos pooled TRỪ-MEAN route", ccos, names)
    show("3. L1 patch-token LN (energy h=0)", l1, names, lower_better=True)


if __name__ == "__main__":
    main()
