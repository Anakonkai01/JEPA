"""CEM planner — pick an action sequence that drives the predicted latent toward
a goal latent, using a trained world model's ``rollout`` (Phase 4).

Cross-Entropy Method: sample N action sequences ~ N(mu, sigma) over horizon H,
roll each out through the model, score by latent distance to goal, refit the
distribution to the top-K elites, repeat for a few iterations, return mu[0].

Defaults from docs/PLAN.md: H=8, N=500, K=50, 4 iterations.
"""
from __future__ import annotations

import torch


class CEMPlanner:
    def __init__(self, model, horizon: int = 8, n_samples: int = 500, n_elite: int = 50,
                 n_iter: int = 4, action_dim: int = 2, action_low=-1.0, action_high=1.0,
                 device: str = "cuda"):
        self.model = model
        self.horizon = horizon
        self.n_samples = n_samples
        self.n_elite = n_elite
        self.n_iter = n_iter
        self.action_dim = action_dim
        self.action_low = action_low
        self.action_high = action_high
        self.device = device

    @torch.no_grad()
    def plan(self, s_t: torch.Tensor, goal_latent: torch.Tensor) -> torch.Tensor:
        """s_t (D,), goal_latent (D,) -> best immediate action (action_dim,).

        TODO(jepa_wm): sample/rollout/score/refit loop using model.rollout.
        """
        raise NotImplementedError("Implement CEM iterations once a model is trained.")
