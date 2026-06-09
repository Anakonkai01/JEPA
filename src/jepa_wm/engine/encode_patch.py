"""Offline PATCH encoding: frames -> frozen V-JEPA 2.1 patch tokens (cached, fp16).

Unlike ``engine.encode`` (which mean-pools to (N,1024)), this keeps the full per-frame
patch map — required by the faithful V-JEPA-2-AC car predictor (docs/VJEPA2_AC_CAR.md).
Each frame is encoded INDEPENDENTLY (image-encoder mode, как V-JEPA 2-AC), no motion.

    frame (B,3,1,256,256) -> encoder -> (B, 256, 1024) patch tokens   [256px -> 16x16 grid]

Per session we write ``<out>/<session>.npy`` = (N, Ntok, 1024) float16, row i aligned
1:1 with row i of ``actions_synced.csv`` (memmap-able for lazy loading). At 256px this
is ~0.5 MB/frame; the whole TowerPro set (~125k frames) is ~66 GB (384px ≈ 2.25×).

    PYTHONPATH=src python scripts/encode_patch.py --raw-dir data/raw_towerpro \
        --out-dir data/latents_towerpro_patch --image-size 256
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from jepa_wm.engine.encode import _FrameSet, load_encoder


@torch.no_grad()
def encode_session(enc, session_dir: Path, out_path: Path, device="cuda",
                   image_size=384, batch_size=16, num_workers=8):
    """Saves a memmap-able .npy of shape (N, Ntok, 1024) float16. Row order == the
    session's actions_synced.csv order (the dataset relies on this 1:1 alignment)."""
    ds = _FrameSet(session_dir, image_size)
    if len(ds) == 0:
        return 0
    dl = DataLoader(ds, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)
    toks = []
    for x, _ in dl:
        x = x.to(device, non_blocking=True).unsqueeze(2)            # (B,3,1,H,W) — per-frame
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
            t = enc(x)                                              # (B, Ntok, 1024)
        toks.append(t.to(torch.float16).cpu().numpy())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, np.concatenate(toks))                        # -> out_path.npy
    return len(ds)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw_towerpro")
    ap.add_argument("--out-dir", default="data/latents_towerpro_patch_384")
    ap.add_argument("--image-size", type=int, default=384)   # native res V-JEPA 2.1 (384->24x24=576 tok)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--num-workers", type=int, default=8)
    ap.add_argument("--sessions", nargs="*", default=None)
    args = ap.parse_args(argv)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    raw, out = Path(args.raw_dir), Path(args.out_dir)
    sessions = args.sessions or sorted(
        p.name for p in raw.glob("session_*") if (p / "actions_synced.csv").exists())
    print(f"[encode_patch] V-JEPA 2.1 ViT-L @{args.image_size}px | {len(sessions)} sessions -> {out}")
    enc = load_encoder(device)
    total = 0
    for i, s in enumerate(sessions):
        op = out / f"{s}.npy"
        if op.exists():
            print(f"  [{i+1}/{len(sessions)}] {s} skip (exists)")
            continue
        t0 = time.time()
        n = encode_session(enc, raw / s, out / s, device, args.image_size, args.batch_size, args.num_workers)
        total += n
        print(f"  [{i+1}/{len(sessions)}] {s}: {n} frames in {time.time()-t0:.0f}s", flush=True)
    print(f"[encode_patch] done: {total} frames -> {out}")


if __name__ == "__main__":
    main()
