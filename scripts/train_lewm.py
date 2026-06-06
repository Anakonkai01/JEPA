#!/usr/bin/env python3
"""Train LeWorldModel (end-to-end pixel JEPA) on recorded RC-car sessions.

    python scripts/train_lewm.py --config configs/train/lewm.yaml configs/model/leworldmodel.yaml
    python scripts/train_lewm.py --config configs/train/lewm.yaml configs/model/leworldmodel.yaml \
                                 --set train.batch_size=32 sigreg.lambd=0.05
"""
import argparse

from jepa_wm.engine.train_lewm import train
from jepa_wm.utils import load_config, merge_overrides


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--set", nargs="*", default=[])
    args = ap.parse_args()
    cfg = merge_overrides(load_config(*args.config), args.set)
    train(cfg)


if __name__ == "__main__":
    main()
