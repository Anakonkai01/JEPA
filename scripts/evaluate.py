#!/usr/bin/env python3
"""Evaluate a trained world model: offline latent metrics (MSE/cosine, multi-step
rollout error) and, later, the online goal-reaching trials (Phase 4).

    python scripts/evaluate.py --config configs/model/vjepa_ac.yaml \
                               --checkpoint checkpoints/vjepa_ac/best.pt
"""
import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.parse_args()
    raise NotImplementedError("Offline eval lands with engine.train; online eval is Phase 4.")


if __name__ == "__main__":
    main()
