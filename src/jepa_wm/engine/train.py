"""Config-driven training loop shared by ACPredictor / LeWorldModel / baselines.

Builds a model from ``cfg["model"]`` via the registry, trains on cached latent
transitions with ``ac_loss``, logs to TensorBoard, checkpoints to
``checkpoints/<run>/``. Entry point: ``scripts/train.py`` (parses configs, calls
``train(cfg)``).

The single-step models (vjepa_ac, action_cnn) take (s_t, a_t) -> ŝ_{t+1};
the recurrent ones (leworldmodel, lstm) take windows. ``cfg["data"]["horizon"]``
should match the model.

TODO(jepa_wm): fill the loop once LatentTransitionDataset is implemented.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader

from ..data import LatentTransitionDataset
from ..models import build_model
from .losses import ac_loss


def train(cfg: dict) -> None:
    device = cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(cfg["model"]).to(device)

    dcfg = cfg["data"]
    train_ds = LatentTransitionDataset(
        dcfg["latents_dir"], sessions=dcfg.get("train_sessions"),
        horizon=dcfg.get("horizon", 1), use_imu=dcfg.get("use_imu", False),
    )
    train_dl = DataLoader(train_ds, batch_size=cfg["train"]["batch_size"], shuffle=True)

    opt = torch.optim.AdamW(model.parameters(), lr=cfg["train"]["lr"],
                            weight_decay=cfg["train"].get("weight_decay", 0.0))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg["train"]["epochs"])

    # TODO(jepa_wm): epoch loop — forward (single-step vs windowed per model kind),
    # ac_loss, backward, step; val MSE/cos; TensorBoard; checkpoint best.
    raise NotImplementedError("Training loop pending LatentTransitionDataset.")
