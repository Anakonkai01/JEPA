"""Offline encoding: run every recorded frame through the frozen V-JEPA encoder
ONCE and cache the latents — training then loads tensors directly (~50-100x
faster than encoding on the fly). See docs/PLAN.md "Key optimization".

Input : data/raw/<session>/frames/*.jpg  (+ actions_synced.csv for alignment)
Output: data/latents/<session>.pt  = {"latents": (N, 1024), "frame_idx": (N,)}

TODO(jepa_wm): implement the frame loader + batched encode loop once
``models.encoders.VJEPAEncoder`` weight-loading is wired up.
"""
from __future__ import annotations

from pathlib import Path


def encode_session(session_dir: str | Path, out_dir: str | Path, encoder, batch_size: int = 32):
    raise NotImplementedError(
        "Implement after VJEPAEncoder loads weights — batched frame encode -> .pt cache."
    )


def main(argv: list[str] | None = None) -> None:
    raise NotImplementedError("CLI wired in scripts/encode_dataset.py once encode_session lands.")
