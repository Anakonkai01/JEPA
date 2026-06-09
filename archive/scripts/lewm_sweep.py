#!/usr/bin/env python3
"""LeWM hyperparameter sweep (single fixed split for fair comparison).

Runs a list of configs sequentially, each with reduced epochs + early stopping,
and dumps final-eval metrics to JSON. Used to pick the best config before a
full/k-fold final run. Logs each run to wandb (group 'lewm_sweep').

    PYTHONPATH=src python scripts/lewm_sweep.py
"""
from __future__ import annotations

import copy
import json
import time

from jepa_wm.engine.train_lewm import train
from jepa_wm.utils import load_config

OUT = "/tmp/lewm_sweep_results.json"

# Each experiment = (name, override dict). Base = TowerPro fs5 block-mean,
# emb256, lambda0.1, steering/throttle scaled to comparable model units.
EXPERIMENTS = [
    ("towerpro_fs5_emb256_l0.1", {}),
    ("towerpro_emb128",          {"model.emb_dim": 128}),
    ("towerpro_emb64",           {"model.emb_dim": 64}),
    ("towerpro_lambda0.05",      {"sigreg.lambd": 0.05}),
    ("towerpro_lambda0.2",       {"sigreg.lambd": 0.2}),
    ("towerpro_fs3",             {"data.frame_skip": 3}),
    ("towerpro_fs10",            {"data.frame_skip": 10}),
]


def set_dotted(cfg, key, val):
    node = cfg
    parts = key.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = val


def main():
    base = load_config("configs/train/lewm.yaml", "configs/model/leworldmodel.yaml")
    # sweep settings: single split, shorter budget, dedicated wandb group
    base["kfold"] = 0
    base["train"]["epochs"] = 70
    base["train"]["patience"] = 12
    base["data"]["raw_dir"] = "data/raw_towerpro"
    base["data"]["frame_skip"] = 5            # base frame skip (overridden per exp)
    base["data"]["action_aggregation"] = "block_mean"
    base["data"]["action_scale"] = [1.0, 6.67]
    base.setdefault("wandb", {})["group"] = "lewm_sweep"

    results = []
    for name, ov in EXPERIMENTS:
        cfg = copy.deepcopy(base)
        for k, v in ov.items():
            set_dotted(cfg, k, v)
        cfg["model"]["num_frames"] = cfg["data"]["seq_len"]
        cfg["train"]["out_dir"] = f"checkpoints/sweep/{name}"
        cfg["wandb"]["name_override"] = name  # (train() names by fold/full; group distinguishes)
        print(f"\n########## SWEEP: {name}  overrides={ov} ##########", flush=True)
        t0 = time.time()
        try:
            summ = train(cfg, fold=None)
            summ["name"] = name
            summ["overrides"] = ov
            summ["minutes"] = round((time.time() - t0) / 60, 1)
            results.append(summ)
        except Exception as e:  # keep going on failure
            print(f"!! {name} FAILED: {e}", flush=True)
            results.append({"name": name, "overrides": ov, "error": str(e)})
        json.dump(results, open(OUT, "w"), indent=2, default=str)

    print("\n================ SWEEP RESULTS ================")
    print(f"{'name':>22} {'val_pred':>9} {'roll@1':>8} {'×ident':>7} {'steer_sens':>11} {'eff_rank':>9}")
    for r in results:
        if "error" in r:
            print(f"{r['name']:>22}  ERROR: {r['error'][:40]}")
            continue
        print(f"{r['name']:>22} {r.get('best_val_pred',0):>9.4f} {r.get('rollout1',0):>8.4f} "
              f"{r.get('rollout1_ratio',0):>7.2f} {r.get('act_steer_sens',0):>11.4f} {r.get('eff_rank',0):>9.1f}")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
