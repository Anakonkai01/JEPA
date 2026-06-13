#!/usr/bin/env python3
"""Synthesize LATERAL-OFFSET pooled latents for recovery training — no GPU.

ROOT problem (CLOSED_LOOP_FAILURE.md, 06-13): teach-down-the-middle data has NO lateral
recovery — once the car drifts off-line the visual policy/CEM has never seen "I'm off to the
side" → no signal to pull back → bung. Meta/ViNG have recovery data; we don't.

This is the DAVE-2 trick adapted to V-JEPA latents: the patch cache stores the 24x24 spatial
token grid per frame. A car laterally offset (or yawed) sees, to first order, a HORIZONTALLY
SHIFTED window of the same scene. So we synthesize an "offset view" by shifting the token grid
along the WIDTH axis with border-replicate padding (keeps all 576 tokens → matches the 576-token
pool computed live at inference), then mean-pool. Pair each shift with a corrective-steer label
(scripts/train_policy_recovery.py) → the policy learns "scene shifted right ⇒ steer left to rejoin".

Token order assumed row-major [H=24, W=24] (standard ViT (h w)->(h w) flatten); shift is along W
(axis=2 after reshape). If the encoder were W-major this would simulate PITCH not yaw — the on-car
recovery probe (lift car left/right, check steer sign) is the ground-truth check for that.

    PYTHONPATH=src python scripts/pool_recovery_latents.py            # both domains, default shifts
Output: <out>/<session>.pt = {"aug": (N, n_shifts, D) f16, "shifts": (n_shifts,) int, "frame_idx": (N,)}
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import torch

DEFAULT_PAIRS = [
    "data/latents_towerpro_patch_384:data/raw_towerpro:data/latents_towerpro_recovery",
    "data/latents_kds_patch_384:data/raw_kds:data/latents_kds_recovery",
]


def read_frame_idx(session_dir: Path) -> list[int]:
    with open(session_dir / "actions_synced.csv") as f:
        return [int(r["frame_idx"]) for r in csv.DictReader(f)]


def pool_session(npy_path: Path, raw_session: Path, out_path: Path,
                 shifts: list[int], grid: int, chunk: int = 256) -> int:
    arr = np.load(npy_path, mmap_mode="r")                  # (N, Ntok, D) fp16
    n, ntok, dim = arr.shape
    assert ntok == grid * grid, f"{npy_path.stem}: Ntok {ntok} != {grid}x{grid}"
    fidx = read_frame_idx(raw_session)
    assert len(fidx) == n, f"{npy_path.stem}: patch rows {n} != actions_synced {len(fidx)}"
    # border-replicate column indices per shift: clip(arange(W)+s, 0, W-1)
    col_idx = {s: np.clip(np.arange(grid) + s, 0, grid - 1) for s in shifts}
    out = np.empty((n, len(shifts), dim), dtype=np.float32)
    for i in range(0, n, chunk):
        blk = arr[i:i + chunk].astype(np.float32).reshape(-1, grid, grid, dim)  # (c,H,W,D)
        for k, s in enumerate(shifts):
            shifted = blk[:, :, col_idx[s], :]                                  # gather along W
            out[i:i + chunk, k] = shifted.mean(axis=(1, 2))                     # pool H,W
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"aug": torch.from_numpy(out).half(),
                "shifts": torch.tensor(shifts, dtype=torch.int16),
                "frame_idx": torch.tensor(fidx)}, out_path)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS, help="patch_dir:raw_dir:out_dir")
    ap.add_argument("--shifts", type=int, nargs="+", default=[-6, -4, -2, 2, 4, 6],
                    help="column shifts (tokens) of the 24-wide grid; +=drift RIGHT (see more right)")
    ap.add_argument("--grid", type=int, default=24)
    ap.add_argument("--chunk", type=int, default=256)
    args = ap.parse_args()
    print(f"[rec] shifts={args.shifts} (token-cols of {args.grid}; +→drift right) | border-replicate pad")

    for pair in args.pairs:
        patch_dir, raw_dir, out_dir = (Path(p) for p in pair.split(":"))
        sessions = sorted(p.stem for p in patch_dir.glob("*.npy"))
        print(f"[rec] {patch_dir} -> {out_dir} ({len(sessions)} sessions)", flush=True)
        total = 0
        for i, s in enumerate(sessions):
            op = out_dir / f"{s}.pt"
            if op.exists():
                continue
            t0 = time.time()
            n = pool_session(patch_dir / f"{s}.npy", raw_dir / s, op, args.shifts, args.grid, args.chunk)
            total += n
            if (i + 1) % 20 == 0 or i == 0:
                print(f"  [{i+1}/{len(sessions)}] {s}: {n} frames in {time.time()-t0:.1f}s", flush=True)
        print(f"[rec] {out_dir}: +{total} frames", flush=True)


if __name__ == "__main__":
    main()
