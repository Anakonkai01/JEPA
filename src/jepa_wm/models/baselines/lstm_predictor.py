"""Baseline 2 — GRU/LSTM latent predictor (~3M params, recurrent).

Lighter recurrent baseline; same I/O contract as LeWorldModel but smaller and
LSTM-based, to isolate the effect of capacity/cell type.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class LSTMPredictor(nn.Module):
    def __init__(self, latent_dim: int = 1024, action_dim: int = 2,
                 hidden_dim: int = 512, predict_residual: bool = True):
        super().__init__()
        self.predict_residual = predict_residual
        self.in_proj = nn.Linear(latent_dim + action_dim, hidden_dim)
        self.lstm = nn.LSTM(hidden_dim, hidden_dim, batch_first=True)
        self.head = nn.Linear(hidden_dim, latent_dim)

    def forward(self, latents: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """latents (B, T, D), actions (B, T, A) -> predicted next latents (B, T, D)."""
        h, _ = self.lstm(self.in_proj(torch.cat([latents, actions], dim=-1)))
        delta = self.head(h)
        return latents + delta if self.predict_residual else delta
