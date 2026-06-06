#!/usr/bin/env python3
"""Train a world model from YAML config(s), with dotted CLI overrides.

    python scripts/train.py --config configs/train/default.yaml configs/model/vjepa_ac.yaml
    python scripts/train.py --config configs/train/default.yaml configs/model/leworldmodel.yaml \
                            --set train.lr=1e-4 train.epochs=120
"""
import argparse

from jepa_wm.engine.train import train
from jepa_wm.utils import load_config, merge_overrides


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True, help="YAML config file(s), merged left-to-right")
    ap.add_argument("--set", nargs="*", default=[], help="dotted overrides, e.g. train.lr=3e-4")
    args = ap.parse_args()

    cfg = load_config(*args.config)
    cfg = merge_overrides(cfg, args.set)
    train(cfg)


if __name__ == "__main__":
    main()
