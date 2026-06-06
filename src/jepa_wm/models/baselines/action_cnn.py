"""Baseline 1 — Action-conditional predictor, Oh et al. 2015 style (~10M params).

Memoryless: action-embedding multiplicatively/additively combined with the
latent, decoded to the next latent. No recurrence. Operates on V-JEPA latents
(not raw pixels) for a fair comparison with ACPredictor.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class ActionCNN(nn.Module):
    def __init__(self, latent_dim: int = 1024, action_dim: int = 2,
                 hidden_dim: int = 1024, predict_residual: bool = True):
        super().__init__()
        self.predict_residual = predict_residual
        self.enc = nn.Sequential(nn.Linear(latent_dim, hidden_dim), nn.ReLU())
        self.act = nn.Linear(action_dim, hidden_dim)
        self.dec = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                                 nn.Linear(hidden_dim, latent_dim))

    def forward(self, s_t: torch.Tensor, a_t: torch.Tensor) -> torch.Tensor:
        fused = self.enc(s_t) * self.act(a_t)          # multiplicative interaction (Oh'15)
        delta = self.dec(fused)
        return s_t + delta if self.predict_residual else delta
