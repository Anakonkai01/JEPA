#!/usr/bin/env python3
"""Derive POOLED session latents from the PATCH cache — no GPU needed.

``encode_dataset.py`` (pooled, for the nav graph + policy prior) and ``encode_patch.py``
(patch tokens, for the control model) run the SAME frozen encoder; the pooled latent is
just the token mean. So when the patch cache already exists (252 GB @384px), the pooled
``.pt`` files can be derived by a chunked CPU mean over the memmap instead of 2 GPU-hours
of re-encoding:

    pooled[i] = patch_npy[i].astype(f32).mean(axis=tokens)     # == encode.py's tok.mean(1)

Output format matches engine.encode exactly: ``<out>/<session>.pt =
{"latents": (N,1024) f32, "frame_idx": (N,)}`` with rows in actions_synced.csv order.
(Tiny fp16-rounding difference vs the GPU path — irrelevant for cosine localize / policy.)

    PYTHONPATH=src python scripts/pool_patch_latents.py \
        --pairs data/latents_towerpro_patch_384:data/raw_towerpro:data/latents_towerpro \
                data/latents_kds_patch_384:data/raw_kds:data/latents_kds
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import torch

DEFAULT_PAIRS = [
    "data/latents_towerpro_patch_384:data/raw_towerpro:data/latents_towerpro",
    "data/latents_kds_patch_384:data/raw_kds:data/latents_kds",
]


def read_frame_idx(session_dir: Path) -> list[int]:
    with open(session_dir / "actions_synced.csv") as f:
        return [int(r["frame_idx"]) for r in csv.DictReader(f)]


def pool_session(npy_path: Path, raw_session: Path, out_path: Path, chunk: int = 128) -> int:
    arr = np.load(npy_path, mmap_mode="r")                  # (N, Ntok, D) fp16
    fidx = read_frame_idx(raw_session)
    assert len(fidx) == arr.shape[0], \
        f"{npy_path.stem}: patch rows {arr.shape[0]} != actions_synced rows {len(fidx)}"
    out = np.empty((arr.shape[0], arr.shape[2]), dtype=np.float32)
    for i in range(0, arr.shape[0], chunk):
        out[i:i + chunk] = arr[i:i + chunk].astype(np.float32).mean(axis=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"latents": torch.from_numpy(out), "frame_idx": torch.tensor(fidx)}, out_path)
    return arr.shape[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS,
                    help="patch_dir:raw_dir:out_dir triplets")
    ap.add_argument("--chunk", type=int, default=128)
    args = ap.parse_args()

    for pair in args.pairs:
        patch_dir, raw_dir, out_dir = (Path(p) for p in pair.split(":"))
        sessions = sorted(p.stem for p in patch_dir.glob("*.npy"))
        print(f"[pool] {patch_dir} -> {out_dir} ({len(sessions)} sessions)", flush=True)
        total = 0
        for i, s in enumerate(sessions):
            op = out_dir / f"{s}.pt"
            if op.exists():
                continue
            t0 = time.time()
            n = pool_session(patch_dir / f"{s}.npy", raw_dir / s, op, args.chunk)
            total += n
            print(f"  [{i+1}/{len(sessions)}] {s}: {n} frames in {time.time()-t0:.0f}s", flush=True)
        print(f"[pool] {out_dir}: +{total} frames", flush=True)


if __name__ == "__main__":
    main()
