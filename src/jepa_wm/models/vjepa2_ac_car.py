"""VJEPA2ACCar — faithful V-JEPA 2-AC adapted to the RC car (docs/VJEPA2_AC_CAR.md).

Self-contained port of Meta's ``VisionTransformerPredictorAC`` (reference/vjepa2/src/
models/ac_predictor.py): a block-causal transformer over a sequence of per-frame PATCH
maps, with action + state tokens interleaved per frame. Predicts the next frame's patch
map. The frozen V-JEPA 2.1 encoder is applied OFFLINE (engine.encode_patch) — this module
operates on cached patch tokens, so the encoder is never in the graph.

Differences from Meta's (deliberate, car-specific):
  * action_dim = 2 (steer, throttle) instead of 7-D end-effector delta;
  * state_dim  = 2 (speed, yaw-rate) instead of 7-D pose — the car's velocity state;
  * learnable temporal + token-type positional embeddings instead of 3D-RoPE (simpler;
    the faithful parts kept are: per-frame patch tokens, interleaved action+state tokens,
    block-causal attention, residual next-state prediction).

Per frame t the token group is ``[action_t, state_t, patch_t(1..N)]`` (N+2 tokens). A
block-causal mask lets a token at frame t attend to all tokens at frames ≤ t. The output
at the patch positions of frame t predicts the patch map of frame t+1 (residual).
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class VJEPA2ACCar(nn.Module):
    def __init__(
        self,
        latent_dim: int = 1024,      # V-JEPA ViT-L token dim
        num_tokens: int = 256,       # patch tokens per frame (256px -> 16x16)
        action_dim: int = 2,
        state_dim: int = 2,
        pred_dim: int = 512,         # predictor hidden width
        depth: int = 8,
        n_heads: int = 8,
        max_frames: int = 16,
        dropout: float = 0.1,
        predict_residual: bool = True,
    ):
        super().__init__()
        self.num_tokens = num_tokens
        self.cond_tokens = 2                       # action + state, prepended per frame
        self.group = num_tokens + self.cond_tokens
        self.predict_residual = predict_residual
        self._mask_cache: dict = {}

        self.patch_embed = nn.Linear(latent_dim, pred_dim)
        self.action_embed = nn.Linear(action_dim, pred_dim)
        self.state_embed = nn.Linear(state_dim, pred_dim)
        # learnable positional embeddings: temporal (per frame) + token-type (a / s / patch-slot)
        self.temporal_pos = nn.Parameter(torch.zeros(1, max_frames, 1, pred_dim))
        self.token_pos = nn.Parameter(torch.zeros(1, 1, self.group, pred_dim))
        nn.init.trunc_normal_(self.temporal_pos, std=0.02)
        nn.init.trunc_normal_(self.token_pos, std=0.02)

        layer = nn.TransformerEncoderLayer(
            d_model=pred_dim, nhead=n_heads, dim_feedforward=pred_dim * 4,
            dropout=dropout, batch_first=True, activation="gelu", norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=depth, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(pred_dim)
        self.head = nn.Linear(pred_dim, latent_dim)

    def _block_causal_mask(self, T: int, device) -> torch.Tensor:
        """(L,L) float mask, 0 = attend, -inf = block. Cached by (T, device)."""
        key = (T, str(device))
        if key not in self._mask_cache:
            L = T * self.group
            fr = torch.arange(L, device=device) // self.group
            allowed = fr[:, None] >= fr[None, :]
            mask = torch.zeros(L, L, device=device)
            mask.masked_fill_(~allowed, float("-inf"))
            self._mask_cache[key] = mask
        return self._mask_cache[key]

    def _embed(self, z, a, s):
        """z (B,T,N,D), a (B,T,A), s (B,T,S) -> token sequence (B, T*group, P)."""
        B, T, N, _ = z.shape
        zt = self.patch_embed(z)                                   # (B,T,N,P)
        at = self.action_embed(a).unsqueeze(2)                     # (B,T,1,P)
        st = self.state_embed(s).unsqueeze(2)                      # (B,T,1,P)
        x = torch.cat([at, st, zt], dim=2)                         # (B,T,group,P)
        x = x + self.temporal_pos[:, :T] + self.token_pos          # add pos emb
        return x.flatten(1, 2)                                     # (B, T*group, P)

    def forward(self, z, a, s):
        """z (B,T,N,D) patch maps, a (B,T,A), s (B,T,S).

        Returns predicted next-frame patch maps ``ẑ`` (B,T,N,D); ``ẑ[:,t]`` is the
        prediction of ``z[:,t+1]`` (residual on ``z[:,t]``). Train with L1 on
        ``ẑ[:,:-1]`` vs ``z[:,1:]``.
        """
        B, T, N, D = z.shape
        x = self._embed(z, a, s)                                   # (B, T*group, P)
        x = self.encoder(x, mask=self._block_causal_mask(T, z.device))
        x = x.view(B, T, self.group, -1)[:, :, self.cond_tokens:]  # patch slots only (B,T,N,P)
        delta = self.head(self.norm(x))                            # (B,T,N,D)
        return z + delta if self.predict_residual else delta

    @torch.no_grad()
    def rollout(self, z0, states, actions, history: int = 2):
        """Autoregressive latent rollout for planning / eval.

        z0      (B, Hctx, N, D)  context patch maps (frames 0..Hctx-1, already observed)
        actions (B, F, A)        action at frame k drives the transition k -> k+1
        states  (B, F, S)        state at frame k (future ones from the bicycle-model
                                 integrator, see planning.dynamics)
        Predicts F future patch maps z1..zF (B, F, N, D). Predicted reps are re-layer-
        normed each step (as V-JEPA 2-AC normalises reps before feeding them back).
        """
        z = z0
        preds = []
        for _ in range(actions.size(1)):
            k = z.size(1)
            lo = max(0, k - history)
            nxt = self.forward(z[:, lo:k], actions[:, lo:k], states[:, lo:k])[:, -1:]
            nxt = F.layer_norm(nxt, (nxt.size(-1),))               # keep reps in LN space
            preds.append(nxt)
            z = torch.cat([z, nxt], dim=1)
        return torch.cat(preds, dim=1)
