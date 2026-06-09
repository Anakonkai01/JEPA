"""GoalPolicyPrior — goal-conditioned behavior-cloning policy used to WARM-START CEM.

PiJEPA-style (arXiv:2603.25981) adaptation for the car: PiJEPA finetunes a generalist
VLA policy and uses its action distribution to warm-start MPPI over a JEPA world model.
We have no language instructions and no VLA — but we DO have ~220k frames of human
goal-reaching driving, so the equivalent prior here is a small goal-conditioned BC MLP:

    a_t = pi( pooled_latent(z_t),  pooled_latent(z_goal),  state_t,  domain )

trained to imitate the recorded action when the "goal" is the frame d steps ahead
(d sampled 1..d_max, same frame_stride as the world model). At plan time its output
initialises CEM's mu (instead of zeros), so CEM starts near a sensible action and
needs fewer samples/iterations — less zigzag, lower latency. CEM still refines under
the world model, so a mediocre prior costs nothing (elites overrule it).

Inputs use the RAW token-mean pooled latent (= ``engine.encode`` output / the nav
latent), LayerNorm'd inside the model; state is z-scored with the world model's
checkpoint stats; action target is RAW [steer, throttle] (throttle up-weighted in
the loss like action_scale, so it isn't drowned by steering).
"""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn


def pooled_dir_for(raw_dir) -> str:
    """data/raw_towerpro -> data/latents_towerpro (the repo's pooled-latent convention)."""
    name = Path(raw_dir).name
    return str(Path(raw_dir).parent / ("latents_" + name.removeprefix("raw_")))


def load_policy(path, device="cpu"):
    """Load a trained prior + meta (saved by scripts/train_policy_prior.py)."""
    ck = torch.load(path, map_location=device, weights_only=False)
    m = ck["meta"]
    model = GoalPolicyPrior(latent_dim=m["latent_dim"], state_dim=m["state_dim"],
                            hidden=m["hidden"], depth=m["depth"], use_domain=m["use_domain"]).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, m


class GoalPolicyPrior(nn.Module):
    def __init__(self, latent_dim: int = 1024, state_dim: int = 12, hidden: int = 512,
                 depth: int = 3, use_domain: bool = True, dropout: float = 0.1):
        super().__init__()
        self.use_domain = use_domain
        self.z_norm = nn.LayerNorm(latent_dim)
        self.g_norm = nn.LayerNorm(latent_dim)
        in_dim = 2 * latent_dim + state_dim + (1 if use_domain else 0)
        layers: list[nn.Module] = []
        for i in range(depth):
            layers += [nn.Linear(in_dim if i == 0 else hidden, hidden), nn.GELU(), nn.Dropout(dropout)]
        layers += [nn.Linear(hidden, 2)]
        self.net = nn.Sequential(*layers)

    def forward(self, z, zg, state, domain=None):
        """z/zg (B,1024) raw pooled latents, state (B,S) z-scored, domain (B,) or scalar.
        Returns RAW (B,2) [steer, throttle] (unclamped — clamp to the action box at use)."""
        parts = [self.z_norm(z), self.g_norm(zg), state]
        if self.use_domain:
            if domain is None:
                raise ValueError("model was trained with a domain token — pass domain=")
            d = torch.as_tensor(domain, dtype=z.dtype, device=z.device).expand(z.size(0))
            parts.append(d.unsqueeze(1))
        return self.net(torch.cat(parts, dim=-1))
