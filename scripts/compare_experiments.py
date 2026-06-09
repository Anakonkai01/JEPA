"""Quick comparison table across all trained checkpoints.

Usage: PYTHONPATH=src python scripts/compare_experiments.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import torch

def load_ckpt_meta(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    val = ckpt.get("val", float("nan"))
    epoch = ckpt.get("epoch", -1)
    cfg = ckpt.get("cfg", {})
    name = cfg.get("wandb", {}).get("group", "?") + "/" + path.parent.name
    # count params from state dict (strip torch.compile prefix if present)
    sd = {k.replace("_orig_mod.", "", 1): v for k, v in ckpt.get("model", {}).items()}
    params_m = sum(v.numel() for v in sd.values() if v.ndim >= 1) / 1e6
    return {"name": name, "best_val": val, "epoch": epoch, "params_m": params_m, "path": str(path)}

CHECKPOINTS = [
    "checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt",
    "checkpoints/vjepa_ac_car_minimal/vjepa_ac_car/best.pt",
    "checkpoints/vjepa_ac_car_residual/vjepa_ac_car/best.pt",
    "checkpoints/vjepa_ac_pool_towerpro/vjepa_ac/best.pt",
]

rows = []
for p in CHECKPOINTS:
    pt = Path(p)
    if pt.exists():
        try:
            rows.append(load_ckpt_meta(pt))
        except Exception as e:
            rows.append({"name": p, "best_val": float("nan"), "epoch": -1, "path": p, "err": str(e)})
    else:
        print(f"[skip] {p} — not trained yet")

if rows:
    print(f"\n{'Model':<45} {'best_val':>10} {'epoch':>7} {'params':>8}")
    print("-" * 73)
    best_val = min(r["best_val"] for r in rows)
    for r in sorted(rows, key=lambda r: r["best_val"]):
        marker = " ★" if r["best_val"] == best_val else ""
        pm = f"{r.get('params_m',0):.1f}M"
        print(f"{r['name']:<45} {r['best_val']:>10.4f} {r['epoch']:>7} {pm:>8}{marker}")
    print()
    print("Note: val loss scales differ (pool=MSE+cos on 1D latent, ac_car=L1 on 256-patch tokens).")
    print("Use rollout@1 ratio to identity for fair comparison.")
