#!/usr/bin/env python3
"""Rollout-vs-identity ratio eval for a VJEPA2ACCar checkpoint, standalone.

Runs the trainer's ``final_eval`` (rollout@k L1 vs identity baseline) on the FROZEN val
split — for when a run died before printing its DONE line, or to compare checkpoints
(e.g. base vs cooldown) on the same split.

    PYTHONPATH=src python scripts/eval_ratio_ac.py \
        --checkpoint checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from jepa_wm.data.ac_clip import ACClipDataset
from jepa_wm.data.dataset import frozen_split
from jepa_wm.engine.train_ac_car import final_eval
from jepa_wm.models import build_model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt")
    ap.add_argument("--split", default=None, help="split.json (default: next to checkpoint)")
    ap.add_argument("--horizon", type=int, default=None, help="rollout steps (default: ckpt cfg eval.horizon)")
    ap.add_argument("--max-n", type=int, default=2000)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict({k.replace("_orig_mod.", "", 1): v for k, v in ckpt["model"].items()})
    model.eval()

    dcfg = cfg["data"]
    raw_roots = dcfg.get("roots") or [{"patch_dir": dcfg["patch_dir"], "raw_dir": dcfg["raw_dir"], "domain_id": 0}]
    use_domain = len(raw_roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in raw_roots)
    for r in raw_roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    sessions = sorted(s for r in raw_roots for s in r["_sessions"])
    split_path = Path(args.split) if args.split else Path(args.checkpoint).parent / "split.json"
    _, val_s, sinfo = frozen_split(split_path, sessions, val_frac=dcfg.get("val_frac", 0.2),
                                   seed=cfg.get("seed", 0), save=False)
    val_set = set(val_s)

    cols = tuple(dcfg.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    kw = dict(horizon=dcfg.get("horizon", 4), frame_stride=dcfg.get("frame_stride", 2),
              state_columns=cols, action_scale=tuple(dcfg.get("action_scale", [1.0, 6.67])),
              state_mean=ckpt["state_mean"].cpu(), state_std=ckpt["state_std"].cpu(),
              max_gap=dcfg.get("max_gap"))
    if use_domain:
        val_roots = [{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                      "sessions": [s for s in r["_sessions"] if s in val_set],
                      "domain_id": r.get("domain_id", 0)} for r in raw_roots]
        ds = ACClipDataset(roots=val_roots, **kw)
    else:
        r0 = raw_roots[0]
        ds = ACClipDataset(r0["patch_dir"], r0["raw_dir"],
                           [s for s in r0["_sessions"] if s in val_set], **kw)

    H = args.horizon or cfg.get("eval", {}).get("horizon", 3)
    src = f"FROZEN <- {split_path}" if sinfo["frozen"] else "deterministic (no split.json!)"
    print(f"[eval_ratio] {args.checkpoint} (ep {ckpt['epoch']}, val {ckpt['val']:.4f})")
    print(f"[eval_ratio] {len(val_s)} val sessions [{src}] | {len(ds)} windows -> "
          f"{min(len(ds), args.max_n)} sampled | horizon {H}")
    mod, idn = final_eval(model, ds, args.device, H, max_n=args.max_n)
    for k in sorted(mod):
        print(f"  rollout@{k}  model {mod[k]:.4f} | identity {idn[k]:.4f} | ratio {mod[k] / max(idn[k], 1e-9):.3f}")


if __name__ == "__main__":
    main()
