#!/usr/bin/env python3
"""Train VJEPA2ACCar (faithful V-JEPA-2-AC for the car).

    python scripts/train_ac_car.py --config configs/train/vjepa_ac_car.yaml configs/model/vjepa_ac_car.yaml
"""
import argparse

from jepa_wm.engine.train_ac_car import train
from jepa_wm.utils import load_config, merge_overrides


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--set", nargs="*", default=[])
    args = ap.parse_args()
    cfg = load_config(*args.config)
    cfg = merge_overrides(cfg, args.set)
    train(cfg)


if __name__ == "__main__":
    main()
