"""Frozen V-JEPA 2.1 encoder wrapper.

⚠️ NEVER backprop through this — the encoder is always frozen (eval + no_grad).
Used only offline by ``engine.encode`` to turn frames into latents; training
loads the cached latents and never touches this module.

Model: ViT-L, fpc64, 256px input. Output spatial tokens
``(B, T/2, H/16, W/16, 1024)`` -> mean-pool -> ``(B, 1024)``.

Loading (see CLAUDE.md "V-JEPA 2.1 Notes"):
  - local checkpoint: ``https://dl.fbaipublicfiles.com/vjepa2/vitl_fpc64_256.pth``
  - HuggingFace (dev): ``facebook/vjepa2-vitl-fpc64-256``
  - torch.hub loading is flaky (fails on Colab) — prefer HF or local path.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class VJEPAEncoder(nn.Module):
    EMBED_DIM = 1024

    def __init__(self, checkpoint: str | None = None, hf_id: str = "facebook/vjepa2-vitl-fpc64-256",
                 device: str = "cuda"):
        super().__init__()
        self.device = device
        self.hf_id = hf_id
        self.checkpoint = checkpoint
        self.backbone: nn.Module | None = None
        # TODO(jepa_wm): load ViT-L weights (local checkpoint preferred, HF fallback),
        # then freeze: for p in self.backbone.parameters(): p.requires_grad_(False)
        raise NotImplementedError("Wire up V-JEPA 2.1 weight loading before encoding.")

    @torch.no_grad()
    def forward(self, frames: torch.Tensor) -> torch.Tensor:
        """frames (B, C, T, H, W) preprocessed to 256px -> pooled latents (B, 1024)."""
        raise NotImplementedError
