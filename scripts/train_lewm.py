#!/usr/bin/env python3
"""Train LeWorldModel (end-to-end pixel JEPA) on recorded RC-car sessions.

Single split:
    python scripts/train_lewm.py --config configs/train/lewm.yaml configs/model/leworldmodel.yaml --set kfold=0
K-fold CV by session (default, kfold>=2 in config) + wandb:
    python scripts/train_lewm.py --config configs/train/lewm.yaml configs/model/leworldmodel.yaml \
                                 --set data.frame_skip=5
"""
import argparse

from jepa_wm.engine.train_lewm import kfold, train
from jepa_wm.utils import load_config, merge_overrides


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--set", nargs="*", default=[])
    args = ap.parse_args()
    cfg = merge_overrides(load_config(*args.config), args.set)
    if cfg.get("kfold", 0) and cfg["kfold"] >= 2:
        kfold(cfg)
    else:
        train(cfg)


if __name__ == "__main__":
    main()
