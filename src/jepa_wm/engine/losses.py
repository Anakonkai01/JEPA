"""World-model training losses.

- ``ac_loss``  : MSE + cosine, for the frozen-V-JEPA AC predictor (vjepa_ac).
- ``SIGReg``   : Sketched-Isotropic-Gaussian Regularizer (anti-collapse) for LeWM.
- ``lewm_loss``: LeWM's two-term objective = MSE next-embedding + λ·SIGReg.

SIGReg is a faithful port of the official le-wm `module.py`.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


def ac_loss(pred: torch.Tensor, target: torch.Tensor, cos_weight: float = 0.5):
    """Returns (total, {"mse":, "cos":}). Shapes (..., D); reduced over all dims."""
    target = target.detach()
    mse = F.mse_loss(pred, target)
    cos = (1.0 - F.cosine_similarity(pred, target, dim=-1)).mean()
    total = mse + cos_weight * cos
    return total, {"mse": mse.detach(), "cos": cos.detach()}


class SIGReg(nn.Module):
    """Sketched-Isotropic-Gaussian Regularizer (single-GPU).

    Projects embeddings onto ``num_proj`` random unit directions and penalises
    the Epps–Pulley normality test statistic of each 1-D projection (vs. the
    standard-normal characteristic function), integrated by trapezoid over
    ``knots`` nodes in [0, 3]. By Cramér–Wold, driving this to 0 pushes the full
    embedding distribution toward an isotropic Gaussian — preventing collapse.
    Faithful port of le-wm `module.py`.
    """

    def __init__(self, knots: int = 17, num_proj: int = 1024):
        super().__init__()
        self.num_proj = num_proj
        t = torch.linspace(0, 3, knots, dtype=torch.float32)
        dt = 3 / (knots - 1)
        weights = torch.full((knots,), 2 * dt, dtype=torch.float32)
        weights[[0, -1]] = dt                      # trapezoid endpoints
        window = torch.exp(-t.square() / 2.0)      # standard-normal char. fn φ₀(t)
        self.register_buffer("t", t)
        self.register_buffer("phi", window)
        self.register_buffer("weights", weights * window)

    def forward(self, proj: torch.Tensor) -> torch.Tensor:
        """proj (T, B, D) -> scalar regularizer (averaged over time & projections)."""
        A = torch.randn(proj.size(-1), self.num_proj, device=proj.device)
        A = A.div_(A.norm(p=2, dim=0))                       # unit-norm directions
        x_t = (proj @ A).unsqueeze(-1) * self.t              # (T, B, num_proj, knots)
        err = (x_t.cos().mean(-3) - self.phi).square() + x_t.sin().mean(-3).square()
        statistic = (err @ self.weights) * proj.size(-2)     # (T, num_proj)
        return statistic.mean()


def lewm_loss(emb: torch.Tensor, next_emb: torch.Tensor, sigreg: SIGReg, lambd: float = 0.1):
    """LeWM objective. emb/next_emb: (B, T, D).

    pred_loss = MSE(emb[:, 1:], next_emb[:, :-1]) ; reg = SIGReg(emb as (T, B, D)).
    Returns (total, {"pred":, "sigreg":}).
    """
    pred = F.mse_loss(next_emb[:, :-1], emb[:, 1:])
    reg = sigreg(emb.transpose(0, 1))
    total = pred + lambd * reg
    return total, {"pred": pred.detach(), "sigreg": reg.detach()}
