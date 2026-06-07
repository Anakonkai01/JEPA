"""CEM planner — pick an action sequence that drives the predicted latent toward
a goal latent, using a trained world model's ``rollout`` (Phase 4).

Cross-Entropy Method: sample N action sequences ~ N(mu, sigma) over horizon H,
roll each out through the model, score by latent distance to goal, refit the
distribution to the top-K elites, repeat for a few iterations, return mu[0].

Defaults from docs/PLAN.md: H=8, N=500, K=50, 4 iterations.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


class CEMPlanner:
    def __init__(self, model, horizon: int = 8, n_samples: int = 500, n_elite: int = 50,
                 n_iter: int = 4, action_dim: int = 2, action_low=-1.0, action_high=1.0,
                 init_std: float = 0.7, min_std: float = 0.05, action_penalty: float = 0.0,
                 smooth_penalty: float = 0.0, fixed_action_tail=None, device: str = "cuda"):
        self.model = model
        self.horizon = horizon
        self.n_samples = n_samples
        self.n_elite = n_elite
        self.n_iter = n_iter
        self.action_dim = action_dim
        self.action_low = torch.as_tensor(action_low, dtype=torch.float32, device=device).expand(action_dim)
        self.action_high = torch.as_tensor(action_high, dtype=torch.float32, device=device).expand(action_dim)
        self.init_std = init_std
        self.min_std = min_std
        self.action_penalty = action_penalty
        self.smooth_penalty = smooth_penalty
        self.fixed_action_tail = None
        if fixed_action_tail is not None:
            self.fixed_action_tail = torch.as_tensor(fixed_action_tail, dtype=torch.float32, device=device)
        self.device = device

    @torch.no_grad()
    def rollout_latent(self, context_latent: torch.Tensor, future_actions: torch.Tensor) -> torch.Tensor:
        """Roll out from latent context using future action candidates.

        Args:
            context_latent: ``(B, Hctx, D)``.
            future_actions: ``(B, horizon, A_model)`` where the first action maps
                the last context frame to the first predicted future latent.
        Returns:
            Predicted future latents ``(B, horizon, D)``.
        """
        hs = self.model.history_size
        emb = context_latent
        preds = []
        # The model's predictor expects an action sequence aligned with the
        # current latent sequence; the last action is the transition we apply.
        prefix = torch.zeros(emb.size(0), max(0, emb.size(1) - 1), future_actions.size(-1),
                             device=emb.device, dtype=future_actions.dtype)
        action_seq = torch.cat([prefix, future_actions], dim=1)
        for t in range(future_actions.size(1)):
            upto = emb.size(1)
            act_emb = self.model.action_encoder(action_seq[:, :upto])
            nxt = self.model.predict(emb[:, -hs:], act_emb[:, -hs:]).float()[:, -1:]
            emb = torch.cat([emb, nxt], dim=1)
            preds.append(nxt)
        return torch.cat(preds, dim=1)

    def _model_actions(self, actions: torch.Tensor) -> torch.Tensor:
        if self.fixed_action_tail is None:
            return actions
        tail = self.fixed_action_tail.view(1, 1, -1).expand(actions.size(0), actions.size(1), -1)
        return torch.cat([actions, tail], dim=-1)

    def _score(self, context_latent: torch.Tensor, goal_latent: torch.Tensor,
               actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        model_actions = self._model_actions(actions)
        preds = self.rollout_latent(context_latent, model_actions)
        goal = goal_latent.view(1, -1).expand(preds.size(0), -1)
        score = F.mse_loss(preds[:, -1], goal, reduction="none").mean(dim=1)
        if self.action_penalty:
            score = score + self.action_penalty * actions.square().mean(dim=(1, 2))
        if self.smooth_penalty and actions.size(1) > 1:
            score = score + self.smooth_penalty * (actions[:, 1:] - actions[:, :-1]).square().mean(dim=(1, 2))
        return score, preds

    @torch.no_grad()
    def plan(self, context_latent: torch.Tensor, goal_latent: torch.Tensor,
             return_info: bool = False):
        """Plan toward ``goal_latent`` and return the first optimized action.

        ``context_latent`` can be ``(Hctx, D)`` or ``(1, Hctx, D)``. The returned
        action is in the model-action units configured for the planner.
        """
        self.model.eval()
        if context_latent.dim() == 2:
            context_latent = context_latent.unsqueeze(0)
        context_latent = context_latent.to(self.device).float()
        goal_latent = goal_latent.to(self.device).float()

        mu = torch.zeros(self.horizon, self.action_dim, device=self.device)
        sigma = torch.full_like(mu, self.init_std)
        best_score = None
        best_seq = None

        for _ in range(self.n_iter):
            eps = torch.randn(self.n_samples, self.horizon, self.action_dim, device=self.device)
            samples = mu.unsqueeze(0) + sigma.unsqueeze(0) * eps
            samples = torch.max(torch.min(samples, self.action_high), self.action_low)
            ctx = context_latent.expand(self.n_samples, -1, -1)
            score, _ = self._score(ctx, goal_latent, samples)
            elite_idx = torch.topk(score, self.n_elite, largest=False).indices
            elites = samples[elite_idx]
            mu = elites.mean(dim=0)
            sigma = elites.std(dim=0).clamp_min(self.min_std)
            cur_best = score[elite_idx[0]]
            if best_score is None or cur_best < best_score:
                best_score = cur_best
                best_seq = samples[elite_idx[0]]

        assert best_seq is not None and best_score is not None
        first = best_seq[0].detach().cpu()
        if not return_info:
            return first
        return first, {
            "score": float(best_score.detach().cpu()),
            "sequence": best_seq.detach().cpu(),
            "mean_sequence": mu.detach().cpu(),
        }
