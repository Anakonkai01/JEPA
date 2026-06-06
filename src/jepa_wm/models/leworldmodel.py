"""LeWorldModel (LeWM) — Stable end-to-end JEPA world model from pixels.

Faithful port of the official implementation (github.com/lucas-maes/le-wm,
`jepa.py` + `module.py`) adapted to standalone training on our RC-car frames
(no stable-pretraining / stable-worldmodel / gym dependency).

Paper: Maes, Le Lidec, Scieur, LeCun, Balestriero — "LeWorldModel: Stable
End-to-End Joint-Embedding Predictive Architecture from Pixels" (2026).
See docs/LeWorldModel.md for the method summary.

Architecture (all trained jointly, from scratch — NO pretrained / frozen encoder):
  - encoder:   ViT-Tiny (patch 14, 12 layers, 3 heads, dim 192) on raw pixels;
               take the [CLS] token -> projector (Linear + BatchNorm).
  - predictor: causal transformer (ViT-S-ish, 6 layers) that predicts the next
               latent autoregressively; actions injected via AdaLN-zero.
  - loss:      MSE next-embedding prediction + λ·SIGReg (anti-collapse).

The BatchNorm projector is required: the ViT's final LayerNorm would otherwise
neutralise the SIGReg anti-collapse objective.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F
from einops import rearrange
from torch import nn
from transformers import ViTConfig, ViTModel


# ───────────────────────── transformer building blocks (port of module.py) ──
def modulate(x, shift, scale):
    """AdaLN-zero modulation."""
    return x * (1 + scale) + shift


class FeedForward(nn.Module):
    def __init__(self, dim, hidden_dim, dropout=0.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(dim), nn.Linear(dim, hidden_dim), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(hidden_dim, dim), nn.Dropout(dropout),
        )

    def forward(self, x):
        return self.net(x)


class Attention(nn.Module):
    def __init__(self, dim, heads=8, dim_head=64, dropout=0.0):
        super().__init__()
        inner_dim = dim_head * heads
        project_out = not (heads == 1 and dim_head == dim)
        self.heads = heads
        self.dropout = dropout
        self.norm = nn.LayerNorm(dim)
        self.to_qkv = nn.Linear(dim, inner_dim * 3, bias=False)
        self.to_out = (nn.Sequential(nn.Linear(inner_dim, dim), nn.Dropout(dropout))
                       if project_out else nn.Identity())

    def forward(self, x, causal=True):
        x = self.norm(x)
        drop = self.dropout if self.training else 0.0
        qkv = self.to_qkv(x).chunk(3, dim=-1)
        q, k, v = (rearrange(t, "b t (h d) -> b h t d", h=self.heads) for t in qkv)
        out = F.scaled_dot_product_attention(q, k, v, dropout_p=drop, is_causal=causal)
        out = rearrange(out, "b h t d -> b t (h d)")
        return self.to_out(out)


class ConditionalBlock(nn.Module):
    """Transformer block with AdaLN-zero action conditioning."""

    def __init__(self, dim, heads, dim_head, mlp_dim, dropout=0.0):
        super().__init__()
        self.attn = Attention(dim, heads=heads, dim_head=dim_head, dropout=dropout)
        self.mlp = FeedForward(dim, mlp_dim, dropout=dropout)
        self.norm1 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm2 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.adaLN_modulation = nn.Sequential(nn.SiLU(), nn.Linear(dim, 6 * dim, bias=True))
        nn.init.constant_(self.adaLN_modulation[-1].weight, 0)
        nn.init.constant_(self.adaLN_modulation[-1].bias, 0)

    def forward(self, x, c):
        shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = \
            self.adaLN_modulation(c).chunk(6, dim=-1)
        x = x + gate_msa * self.attn(modulate(self.norm1(x), shift_msa, scale_msa))
        x = x + gate_mlp * self.mlp(modulate(self.norm2(x), shift_mlp, scale_mlp))
        return x


class _CondTransformer(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, depth, heads, dim_head,
                 mlp_dim, dropout=0.0):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, hidden_dim) if input_dim != hidden_dim else nn.Identity()
        self.cond_proj = nn.Linear(input_dim, hidden_dim) if input_dim != hidden_dim else nn.Identity()
        self.layers = nn.ModuleList(
            [ConditionalBlock(hidden_dim, heads, dim_head, mlp_dim, dropout) for _ in range(depth)]
        )
        self.norm = nn.LayerNorm(hidden_dim)
        self.output_proj = nn.Linear(hidden_dim, output_dim) if hidden_dim != output_dim else nn.Identity()

    def forward(self, x, c):
        x = self.input_proj(x)
        c = self.cond_proj(c)
        for block in self.layers:
            x = block(x, c)
        return self.output_proj(self.norm(x))


class ActionEmbedder(nn.Module):
    """Embed an action sequence (B, T, A) -> (B, T, emb_dim)  (port of Embedder)."""

    def __init__(self, input_dim, smoothed_dim, emb_dim, mlp_scale=4):
        super().__init__()
        self.patch_embed = nn.Conv1d(input_dim, smoothed_dim, kernel_size=1, stride=1)
        self.embed = nn.Sequential(
            nn.Linear(smoothed_dim, mlp_scale * emb_dim), nn.SiLU(),
            nn.Linear(mlp_scale * emb_dim, emb_dim),
        )

    def forward(self, x):
        x = x.float().permute(0, 2, 1)
        x = self.patch_embed(x).permute(0, 2, 1)
        return self.embed(x)


class ARPredictor(nn.Module):
    """Autoregressive (causal) next-latent predictor with AdaLN action conditioning."""

    def __init__(self, *, num_frames, depth, heads, mlp_dim, input_dim, hidden_dim,
                 output_dim=None, dim_head=64, dropout=0.0, emb_dropout=0.0):
        super().__init__()
        self.pos_embedding = nn.Parameter(torch.randn(1, num_frames, input_dim))
        self.dropout = nn.Dropout(emb_dropout)
        self.transformer = _CondTransformer(
            input_dim, hidden_dim, output_dim or input_dim, depth, heads, dim_head, mlp_dim, dropout)

    def forward(self, x, c):
        T = x.size(1)
        x = self.dropout(x + self.pos_embedding[:, :T])
        return self.transformer(x, c)


def _projector(in_dim, out_dim):
    """1-layer MLP + BatchNorm (replaces the ViT final LayerNorm for SIGReg)."""
    return nn.Sequential(nn.Linear(in_dim, out_dim), nn.BatchNorm1d(out_dim))


# ─────────────────────────────────────────────────────────── LeWM model ─────
class LeWorldModel(nn.Module):
    def __init__(
        self,
        action_dim: int = 2,
        emb_dim: int = 256,
        num_frames: int = 4,
        history_size: int = 3,
        # encoder (ViT-Tiny)
        enc_image_size: int = 224,
        enc_patch_size: int = 14,
        enc_hidden: int = 192,
        enc_layers: int = 12,
        enc_heads: int = 3,
        # predictor
        pred_depth: int = 6,
        pred_heads: int = 16,
        pred_dim_head: int = 24,
        pred_hidden: int = 384,
        pred_dropout: float = 0.1,
        action_smoothed_dim: int = 16,
    ):
        super().__init__()
        self.emb_dim = emb_dim
        self.history_size = history_size

        cfg = ViTConfig(
            hidden_size=enc_hidden, num_hidden_layers=enc_layers, num_attention_heads=enc_heads,
            intermediate_size=enc_hidden * 4, image_size=enc_image_size, patch_size=enc_patch_size,
            num_channels=3,
        )
        self.encoder = ViTModel(cfg, add_pooling_layer=False)
        self.projector = _projector(enc_hidden, emb_dim)

        self.action_encoder = ActionEmbedder(action_dim, action_smoothed_dim, emb_dim)
        self.predictor = ARPredictor(
            num_frames=num_frames, depth=pred_depth, heads=pred_heads, dim_head=pred_dim_head,
            mlp_dim=pred_hidden * 4, input_dim=emb_dim, hidden_dim=pred_hidden, output_dim=emb_dim,
            dropout=pred_dropout, emb_dropout=pred_dropout,
        )
        self.pred_proj = _projector(emb_dim, emb_dim)

    # -- encode / predict -----------------------------------------------------
    def encode(self, pixels: torch.Tensor) -> torch.Tensor:
        """pixels (B, T, C, H, W) -> latent (B, T, D)."""
        b = pixels.size(0)
        flat = rearrange(pixels, "b t c h w -> (b t) c h w").float()
        out = self.encoder(flat, interpolate_pos_encoding=True)
        cls = out.last_hidden_state[:, 0]
        emb = self.projector(cls)
        return rearrange(emb, "(b t) d -> b t d", b=b)

    def predict(self, emb: torch.Tensor, act_emb: torch.Tensor) -> torch.Tensor:
        """emb (B, T, D), act_emb (B, T, D) -> predicted next latent (B, T, D)."""
        b = emb.size(0)
        preds = self.predictor(emb, act_emb)
        preds = self.pred_proj(rearrange(preds, "b t d -> (b t) d"))
        return rearrange(preds, "(b t) d -> b t d", b=b)

    def forward(self, pixels: torch.Tensor, actions: torch.Tensor):
        """pixels (B, T, C, H, W), actions (B, T, A).

        Returns (emb, next_emb) both (B, T, D). The prediction loss aligns
        next_emb[:, :-1] with emb[:, 1:]; SIGReg is applied to emb.
        """
        emb = self.encode(pixels)
        act_emb = self.action_encoder(actions)
        next_emb = self.predict(emb, act_emb)
        return emb, next_emb

    # -- inference: autoregressive latent rollout (for planning) --------------
    @torch.no_grad()
    def rollout(self, pixels_ctx: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """pixels_ctx (B, H, C, H, W) context frames, actions (B, T, A) with T>=H.

        Returns predicted latents for the steps after the context (B, T-H, D).
        """
        hs = self.history_size
        emb = self.encode(pixels_ctx)                       # (B, H, D)
        n_steps = actions.size(1) - emb.size(1)
        preds = []
        for t in range(n_steps):
            act_emb = self.action_encoder(actions[:, : emb.size(1)])
            nxt = self.predict(emb[:, -hs:], act_emb[:, -hs:])[:, -1:]   # (B,1,D)
            emb = torch.cat([emb, nxt], dim=1)
            preds.append(nxt)
        return torch.cat(preds, dim=1) if preds else emb[:, :0]
