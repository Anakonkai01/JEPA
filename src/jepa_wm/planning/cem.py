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


class CEMPlannerLatent:
    """CEM for a *latent* world model exposing ``rollout(s0, actions)`` directly
    (the frozen-encoder ``vjepa_ac`` / ``ACPredictor``: state is one latent ``(B,D)``,
    no history/action-encoder, unlike ``LeWorldModel`` which ``CEMPlanner`` targets).

    Latents are assumed already standardized the way the model was trained — the
    caller z-scores ``context``/``goal`` with the checkpoint's ``lat_mean/lat_std``.
    ``action_low``/``action_high`` may be per-dim (e.g. throttle clamped to the
    car's safe envelope ``[-0.16, 0.15]``).
    """

    def __init__(self, model, horizon: int = 8, n_samples: int = 256, n_elite: int = 32,
                 n_iter: int = 4, action_dim: int = 2, action_low=-1.0, action_high=1.0,
                 init_std: float = 0.5, min_std: float = 0.05, action_penalty: float = 0.0,
                 smooth_penalty: float = 0.0, device: str = "cuda"):
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
        self.device = device

    @torch.no_grad()
    def score(self, s0: torch.Tensor, goal: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """Final-latent MSE to goal for each action sequence.

        Args: ``s0`` ``(B,D)`` or ``(D,)``; ``goal`` ``(D,)``; ``actions`` ``(B,H,A)``.
        """
        if s0.dim() == 1:
            s0 = s0.unsqueeze(0)
        if s0.size(0) == 1 and actions.size(0) > 1:
            s0 = s0.expand(actions.size(0), -1)
        preds = self.model.rollout(s0.to(self.device).float(), actions.to(self.device).float())  # (B,H,D)
        g = goal.view(1, -1).to(self.device).float().expand(preds.size(0), -1)
        score = F.mse_loss(preds[:, -1], g, reduction="none").mean(dim=1)
        if self.action_penalty:
            score = score + self.action_penalty * actions.square().mean(dim=(1, 2))
        if self.smooth_penalty and actions.size(1) > 1:
            score = score + self.smooth_penalty * (actions[:, 1:] - actions[:, :-1]).square().mean(dim=(1, 2))
        return score

    @torch.no_grad()
    def plan(self, context_latent: torch.Tensor, goal_latent: torch.Tensor, return_info: bool = False):
        """Plan toward ``goal_latent`` (z-scored); return the first optimized action."""
        self.model.eval()
        s0 = context_latent.view(-1).to(self.device).float()
        goal = goal_latent.view(-1).to(self.device).float()

        mu = torch.zeros(self.horizon, self.action_dim, device=self.device)
        sigma = torch.full_like(mu, self.init_std)
        best_score = None
        best_seq = None
        for _ in range(self.n_iter):
            eps = torch.randn(self.n_samples, self.horizon, self.action_dim, device=self.device)
            samples = torch.max(torch.min(mu + sigma * eps, self.action_high), self.action_low)
            score = self.score(s0, goal, samples)
            elite_idx = torch.topk(score, self.n_elite, largest=False).indices
            elites = samples[elite_idx]
            mu = elites.mean(dim=0)
            sigma = elites.std(dim=0).clamp_min(self.min_std)
            if best_score is None or score[elite_idx[0]] < best_score:
                best_score = score[elite_idx[0]]
                best_seq = samples[elite_idx[0]]
        assert best_seq is not None
        first = best_seq[0].detach().cpu()
        if not return_info:
            return first
        return first, {"score": float(best_score.detach().cpu()),
                       "sequence": best_seq.detach().cpu()}


class CEMPlannerAC:
    """CEM for VJEPA2ACCar (patch-token world model + bicycle-model state integrator).

    Plans raw actions ``[steer, throttle]`` to reach a goal patch map, by (a) integrating
    the [speed,yaw_rate] state forward with ``CarDynamics`` (raw units), (b) rolling the
    patch tokens forward with the predictor (scaled actions + z-scored state), and scoring
    the final predicted patch map's L1 distance to the goal (V-JEPA 2 energy, eq. 5).

    Units: samples are RAW actions (steer∈[-1,1], throttle∈[throttle_min,throttle_max]);
    the predictor sees ``raw*action_scale`` and z-scored state; the goal/context tokens must
    be per-token layer-normed (the same normalisation the dataset applies). Returns the first
    raw action.

    ``domain``: models trained multi-root (KDS+TowerPro) take action_dim=3 with a constant
    domain token appended (0=KDS, 1=TowerPro). Set it here (or per-call in ``plan``/``score``)
    so the planner appends the same column the dataset did; None = 2-D action model.
    """

    def __init__(self, model, dynamics, state_mean, state_std,
                 action_scale=(1.0, 6.67), horizon: int = 4, n_samples: int = 128,
                 n_elite: int = 16, n_iter: int = 4, throttle_min=-0.16, throttle_max=0.15,
                 history: int = 2, init_std: float = 0.5, min_std: float = 0.05,
                 prev_action_idx=None, domain=None, device: str = "cuda"):
        self.model = model.eval()
        self.dyn = dynamics
        self.sm = state_mean.to(device).float(); self.ss = state_std.to(device).float()
        self.ascale = torch.as_tensor(action_scale, dtype=torch.float32, device=device)
        self.H = horizon; self.n_samples = n_samples; self.n_elite = n_elite; self.n_iter = n_iter
        self.history = history; self.init_std = init_std; self.min_std = min_std
        self.low = torch.tensor([-1.0, throttle_min], device=device)
        self.high = torch.tensor([1.0, throttle_max], device=device)
        # P2: nếu state có prev-action (2 cột cuối), truyền tuple chỉ số → rollout set chúng = action
        # ứng viên của bước trước (khớp lúc train: state[t] chứa action[t-1]). None = state không có prev-action.
        self.prev_idx = list(prev_action_idx) if prev_action_idx is not None else None
        self.domain = None if domain is None else float(domain)
        self.device = device

    def _states_raw(self, s0_raw, raw_actions):
        """s0_raw (S,), raw_actions (B,H,2) -> raw states (B,H,S) integrated by dynamics
        (speed + yaw from the action; prev-action slots set to the prior candidate action; rest held)."""
        B = raw_actions.size(0); S = s0_raw.numel()
        s = s0_raw.to(self.device).float().view(1, S).expand(B, S).contiguous()
        out = [s]                                          # s0: prev-action đã có sẵn trong s0_raw
        for k in range(1, self.H):
            s = self.dyn.step(s, raw_actions[:, k - 1])    # dyn.step trả tensor clone → set in-place an toàn
            if self.prev_idx is not None:
                s[:, self.prev_idx] = raw_actions[:, k - 1]   # state[k] mang action[k-1] (gây transition k-1→k)
            out.append(s)
        return torch.stack(out, dim=1)

    @torch.no_grad()
    def score(self, z0, s0_raw, goal, raw_actions, domain=None):
        """z0 (1,N,D) z-scored, s0_raw (S,) raw, goal (N,D) z-scored, raw_actions (B,H,2).
        ``domain`` overrides the planner default for this call (multi-root models)."""
        B = raw_actions.size(0)
        states_z = (self._states_raw(s0_raw, raw_actions) - self.sm) / self.ss      # (B,H,S)
        scaled = raw_actions * self.ascale                                          # (B,H,2)
        dom = self.domain if domain is None else float(domain)
        if dom is not None:                                                          # action_dim=3 model
            dcol = torch.full((B, scaled.size(1), 1), dom, device=scaled.device, dtype=scaled.dtype)
            scaled = torch.cat([scaled, dcol], dim=-1)                               # (B,H,3)
        z0b = z0.unsqueeze(0).expand(B, -1, -1, -1).contiguous()                    # (B,1,N,D)
        preds = self.model.rollout(z0b, states_z, scaled, history=self.history)     # (B,H,N,D)
        final = preds[:, -1]                                                        # (B,N,D)
        return (final - goal.unsqueeze(0)).abs().mean(dim=(1, 2))                    # (B,)

    @torch.no_grad()
    def plan(self, z0, s0_raw, goal, return_info: bool = False, domain=None):
        z0 = z0.to(self.device).float(); goal = goal.to(self.device).float()
        mu = torch.zeros(self.H, 2, device=self.device)
        mu[:, 1] = (self.low[1] + self.high[1]) / 2                                 # throttle mid-box
        sigma = torch.full((self.H, 2), self.init_std, device=self.device)
        best_s, best_seq = None, None
        for _ in range(self.n_iter):
            eps = torch.randn(self.n_samples, self.H, 2, device=self.device)
            samp = torch.max(torch.min(mu + sigma * eps, self.high), self.low)
            sc = self.score(z0, s0_raw, goal, samp, domain=domain)
            elite = torch.topk(sc, self.n_elite, largest=False).indices
            mu = samp[elite].mean(0); sigma = samp[elite].std(0).clamp_min(self.min_std)
            if best_s is None or sc[elite[0]] < best_s:
                best_s, best_seq = sc[elite[0]], samp[elite[0]]
        first = best_seq[0].detach().cpu()
        if not return_info:
            return first
        return first, {"score": float(best_s), "sequence": best_seq.detach().cpu()}


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
