#!/usr/bin/env python3
"""Policy action-recovery theo BUCKET |teacher steer| — policy có tái tạo cú-bẻ-LỚN
(proxy recovery) không, hay chỉ giỏi đi thẳng? Chạy CPU. So cd4 policy vs đường-thẳng-ngu."""
import sys; sys.path.insert(0, "scripts")
from pathlib import Path
import numpy as np, torch
from train_policy_prior import PolicyDataset, load_split_and_roots
from jepa_wm.data.dataset import frozen_split
from jepa_wm.models.policy_prior import load_policy

WM = "checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt"
POL = sys.argv[1] if len(sys.argv) > 1 else "checkpoints/policy_prior_cd4/best.pt"
ckpt = torch.load(WM, map_location="cpu", weights_only=False)
cfg, roots, sessions = load_split_and_roots(ckpt)
d_ = cfg["data"]; cols = tuple(d_["state_columns"]); stride = d_.get("frame_stride", 2)
sm, ss = ckpt["state_mean"].float(), ckpt["state_std"].float()
use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)
_, val_s, _ = frozen_split(Path(WM).parent / "split.json", sessions,
                           val_frac=d_.get("val_frac", 0.2), seed=cfg.get("seed", 0), save=False)
va = PolicyDataset(roots, val_s, cols, sm, ss, stride, d_max=8, seed=1)
policy, meta = load_policy(POL, device="cpu")
print(f"policy {POL} | {len(va)} val anchors")

buckets = [(0, 0.05), (0.05, 0.15), (0.15, 0.4), (0.4, 0.7), (0.7, 1.01)]
ds = {b: [] for b in buckets}; sgn = {b: [] for b in buckets}; dthr = {b: [] for b in buckets}
N = min(16000, len(va)); idx = np.random.default_rng(0).choice(len(va), N, replace=False)
with torch.no_grad():
    for st in range(0, N, 2048):
        sel = idx[st:st + 2048]; items = [va[int(k)] for k in sel]
        z = torch.stack([it["z"] for it in items]); zg = torch.stack([it["zg"] for it in items])
        s = torch.stack([it["s"] for it in items]); dom = torch.stack([it["dom"] for it in items])
        a = torch.stack([it["a"] for it in items])
        pred = policy(z, zg, s, dom if use_domain else None)
        for k in range(len(sel)):
            tea = float(a[k, 0])
            for b in buckets:
                if b[0] <= abs(tea) < b[1]:
                    ds[b].append(abs(float(pred[k, 0]) - tea))
                    dthr[b].append(abs(float(pred[k, 1]) - float(a[k, 1])))
                    sgn[b].append(np.sign(float(pred[k, 0])) == np.sign(tea))
                    break
print(f"\n{'bucket |tea|':>13} {'n':>6} {'med|Δsteer|':>11} {'med|Δthrot|':>11} {'sign-match':>10}")
for b in buckets:
    if not ds[b]:
        continue
    sm_ = float("nan") if b[0] < 0.15 else 100 * np.mean(sgn[b])
    print(f"{f'[{b[0]:.2f},{b[1]:.2f})':>13} {len(ds[b]):>6} {np.median(ds[b]):>11.3f} "
          f"{np.median(dthr[b]):>11.3f} {('—' if b[0]<0.15 else f'{sm_:.0f}%'):>10}")
print("\nĐọc: bucket cao (|tea|>0.4 = cú bẻ lớn/recovery) mà |Δsteer| vẫn nhỏ + sign-match cao")
print("     → policy TÁI TẠO được recovery (không chỉ giỏi đi thẳng).")
