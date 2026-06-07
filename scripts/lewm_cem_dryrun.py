#!/usr/bin/env python3
"""Offline CEM planning dry-run for a trained LeWorldModel.

This never talks to the car. It uses held-out recorded windows, picks a future
latent from the same window as the goal, and compares CEM action sequences
against random sequences and the recorded action sequence under the model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

from jepa_wm.data import FrameSequenceDataset, list_sessions, split_sessions
from jepa_wm.models.leworldmodel import LeWorldModel
from jepa_wm.planning.cem import CEMPlanner


def _data_source(cfg, override):
    if override:
        return override[0] if len(override) == 1 else override
    d = cfg.get("data", {})
    return d.get("raw_dirs") or d.get("raw_dir", "data/raw")


def _json_safe(x):
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


@torch.no_grad()
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--raw-dir", nargs="+", default=None)
    ap.add_argument("--seq-len", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-cases", type=int, default=16)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--elite", type=int, default=32)
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    cfg = ckpt["cfg"]
    mcfg = cfg["model"]
    model = LeWorldModel(**{k: v for k, v in mcfg.items() if k != "name"}).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    source = _data_source(cfg, args.raw_dir)
    sessions = list_sessions(source)
    _, val_s = split_sessions(sessions, val_frac=cfg["data"].get("val_frac", 0.2), seed=cfg.get("seed", 0))
    ds = FrameSequenceDataset(
        source, sessions=val_s, seq_len=args.seq_len,
        frame_skip=cfg["data"].get("frame_skip", 1), stride=4,
        image_size=cfg["data"].get("image_size", 224),
        action_keys=tuple(cfg["data"].get("action_keys", ("steering", "throttle"))),
        action_scale=cfg["data"].get("action_scale"),
        action_aggregation=cfg["data"].get("action_aggregation", "sample"),
        domain_token=cfg["data"].get("domain_token", "none"),
    )
    n = min(len(ds), max(args.max_cases, args.batch_size))
    dl = DataLoader(Subset(ds, list(range(n))), batch_size=args.batch_size, shuffle=False,
                    num_workers=args.num_workers)

    history = int(mcfg["history_size"])
    base_action_dim = len(cfg["data"].get("action_keys", ("steering", "throttle")))
    rows = []
    for batch in dl:
        px = batch["pixels"].to(device)
        ac = batch["actions"].to(device)
        z = model.encode(px).float()
        max_h = min(args.horizon, z.size(1) - history)
        if max_h <= 0:
            continue
        for i in range(z.size(0)):
            if len(rows) >= args.max_cases:
                break
            fixed_tail = None
            if ac.size(-1) > base_action_dim:
                fixed_tail = ac[i, 0, base_action_dim:].detach()
            planner = CEMPlanner(
                model, horizon=max_h, n_samples=args.samples, n_elite=args.elite, n_iter=args.iters,
                action_dim=base_action_dim, action_low=-1.0, action_high=1.0,
                fixed_action_tail=fixed_tail, device=device,
            )
            ctx = z[i, :history]
            goal = z[i, history + max_h - 1]
            _, info = planner.plan(ctx, goal, return_info=True)

            ctx_b = ctx.unsqueeze(0).expand(args.samples, -1, -1)
            rnd = torch.empty(args.samples, max_h, base_action_dim, device=device).uniform_(-1.0, 1.0)
            rnd_score, _ = planner._score(ctx_b, goal, rnd)
            teacher = ac[i, history - 1:history - 1 + max_h, :base_action_dim].unsqueeze(0)
            teacher_score, _ = planner._score(ctx.unsqueeze(0), goal, teacher)
            rows.append({
                "cem_score": info["score"],
                "random_mean": float(rnd_score.mean().cpu()),
                "random_best": float(rnd_score.min().cpu()),
                "teacher_score": float(teacher_score.item()),
                "first_action": [float(v) for v in info["sequence"][0].tolist()],
            })
        if len(rows) >= args.max_cases:
            break

    def mean(key):
        return float(np.mean([r[key] for r in rows])) if rows else float("nan")

    summary = {
        "checkpoint": args.checkpoint,
        "device": device,
        "cases": len(rows),
        "horizon": args.horizon,
        "cem_score": mean("cem_score"),
        "random_mean": mean("random_mean"),
        "random_best": mean("random_best"),
        "teacher_score": mean("teacher_score"),
        "cem_vs_random_mean": mean("cem_score") / max(mean("random_mean"), 1e-9),
        "cem_vs_teacher": mean("cem_score") / max(mean("teacher_score"), 1e-9),
        "rows": rows,
    }
    print(json.dumps(_json_safe(summary), indent=2))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(_json_safe(summary), f, indent=2)


if __name__ == "__main__":
    main()
