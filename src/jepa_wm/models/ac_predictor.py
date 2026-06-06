"""v-jepa-2.1-ac — the Action-Conditioned latent predictor (main contribution).

Given the current frozen V-JEPA latent ``s_t`` and an action ``a_t``, predict the
next latent ``ŝ_{t+1}``. Trained with MSE + cosine on the frozen target latent
(see ``engine.losses.ac_loss``). Small (~5M params) — the encoder does the heavy
lifting; this only learns "which action moves the latent which way".

This single-step head predicts a residual ``Δ`` (``ŝ_{t+1} = s_t + Δ``), which is
much easier than predicting the absolute latent. For multi-step rollout (CEM
planning) the head is applied autoregressively.

NOTE: operates on the mean-pooled latent (B, D). A spatial-token variant
(transformer over the (T/2·H/16·W/16) tokens) is a future option — left as TODO.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class ACPredictor(nn.Module):
    def __init__(
        self,
        latent_dim: int = 1024,
        action_dim: int = 2,
        hidden_dim: int = 512,
        n_layers: int = 2,
        n_heads: int = 8,
        dropout: float = 0.0,
        predict_residual: bool = True,
    ):
        super().__init__()
        self.predict_residual = predict_residual
        self.latent_proj = nn.Linear(latent_dim, hidden_dim)
        self.action_proj = nn.Linear(action_dim, hidden_dim)

        layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim, nhead=n_heads, dim_feedforward=hidden_dim * 4,
            dropout=dropout, batch_first=True, activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.head = nn.Linear(hidden_dim, latent_dim)

    def forward(self, s_t: torch.Tensor, a_t: torch.Tensor) -> torch.Tensor:
        """s_t (B, D), a_t (B, A) -> ŝ_{t+1} (B, D)."""
        tokens = torch.stack([self.latent_proj(s_t), self.action_proj(a_t)], dim=1)  # (B, 2, H)
        fused = self.encoder(tokens)[:, 0]                                            # (B, H) latent slot
        delta = self.head(fused)                                                      # (B, D)
        return s_t + delta if self.predict_residual else delta

    @torch.no_grad()
    def rollout(self, s_0: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """s_0 (B, D), actions (B, H, A) -> predicted latents (B, H, D)."""
        s, preds = s_0, []
        for t in range(actions.shape[1]):
            s = self.forward(s, actions[:, t])
            preds.append(s)
        return torch.stack(preds, dim=1)
