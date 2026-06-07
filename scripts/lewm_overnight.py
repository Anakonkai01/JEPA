#!/usr/bin/env python3
"""Run the overnight LeWorldModel experiment queue.

The queue is intentionally offline-only: train/evaluate checkpoints, run CEM
planner dry-runs on recorded validation windows, and write reports. It never
opens serial/USB/network control links to the car.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from jepa_wm.data import list_sessions, normalize_roots
from jepa_wm.engine.train_lewm import train
from jepa_wm.utils import load_config


COMMON = {
    "kfold": 0,
    "data.frame_skip": 5,
    "data.action_aggregation": "block_mean",
    "data.action_scale": [1.0, 6.67],
    "train.epochs": 300,
    "train.patience": 30,
    "train.batch_size": 96,
    "train.num_workers": 8,
    "eval.seq_len": 12,
    "eval.max_batches": 20,
}


EXPERIMENTS = [
    {
        "name": "towerpro_fs5_blockmean_scaled_emb256_l0.1",
        "set": {"data.raw_dir": "data/raw_towerpro"},
    },
    {
        "name": "towerpro_fs5_blockmean_scaled_emb128_l0.1",
        "set": {"data.raw_dir": "data/raw_towerpro", "model.emb_dim": 128},
    },
    {
        "name": "towerpro_fs3_blockmean_scaled_emb256_l0.1",
        "set": {"data.raw_dir": "data/raw_towerpro", "data.frame_skip": 3},
    },
    {
        "name": "towerpro_fs5_blockmean_scaled_emb256_l0.2",
        "set": {"data.raw_dir": "data/raw_towerpro", "sigreg.lambd": 0.2},
    },
    {
        "name": "kds_pretrain_fs5_then_towerpro_finetune",
        "stages": [
            {
                "suffix": "pretrain_kds",
                "set": {"data.raw_dir": "data/raw", "train.epochs": 180, "train.patience": 20},
            },
            {
                "suffix": "finetune_towerpro",
                "set": {
                    "data.raw_dir": "data/raw_towerpro",
                    "train.epochs": 220,
                    "train.patience": 30,
                    "train.lr": 1.0e-4,
                },
                "init_from_previous": True,
            },
        ],
    },
    {
        "name": "mixed_old_new_naive_fs5",
        "set": {
            "data.raw_dirs": [
                {"path": "data/raw", "domain": "kds680hv", "domain_id": 0},
                {"path": "data/raw_towerpro", "domain": "towerpro", "domain_id": 1},
            ],
            "data.raw_dir": None,
        },
    },
    {
        "name": "mixed_old_new_domain_token_fs5",
        "set": {
            "data.raw_dirs": [
                {"path": "data/raw", "domain": "kds680hv", "domain_id": 0},
                {"path": "data/raw_towerpro", "domain": "towerpro", "domain_id": 1},
            ],
            "data.raw_dir": None,
            "data.domain_token": "scalar",
            "model.action_dim": 3,
        },
    },
]


def set_dotted(cfg: dict, key: str, val) -> None:
    node = cfg
    parts = key.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = val


def apply_overrides(cfg: dict, overrides: dict) -> dict:
    out = copy.deepcopy(cfg)
    for k, v in overrides.items():
        set_dotted(out, k, copy.deepcopy(v))
    return out


def json_safe(x):
    if isinstance(x, dict):
        return {str(k): json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_safe(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, Path):
        return str(x)
    return x


def count_rows(csv_path: Path) -> int:
    with open(csv_path) as f:
        return max(0, sum(1 for _ in f) - 1)


def data_manifest(source) -> dict:
    roots = normalize_roots(source)
    domains = []
    total_sessions = 0
    total_frames = 0
    for root in roots:
        sessions = list_sessions(root.path)
        frames = 0
        for s in sessions:
            frames += count_rows(root.path / s / "actions_synced.csv")
        domains.append({"domain": root.domain, "path": str(root.path), "sessions": len(sessions), "frames": frames})
        total_sessions += len(sessions)
        total_frames += frames
    return {"domains": domains, "sessions": total_sessions, "frames": total_frames}


def checkpoint_path(out_dir: Path) -> Path:
    return out_dir / "leworldmodel" / "best.pt"


def run_cem_dryrun(ckpt: Path, out: Path, max_cases: int, horizon: int) -> dict:
    env = os.environ.copy()
    src = str(Path.cwd() / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [
        sys.executable, "scripts/lewm_cem_dryrun.py",
        "--checkpoint", str(ckpt),
        "--max-cases", str(max_cases),
        "--horizon", str(horizon),
        "--out", str(out),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    if proc.returncode != 0:
        return {"error": proc.stderr[-4000:] or proc.stdout[-4000:], "returncode": proc.returncode}
    try:
        return json.loads(out.read_text())
    except Exception:
        return {"stdout": proc.stdout[-4000:]}


def write_report(run_dir: Path, results: list[dict], preflight: dict) -> None:
    lines = [
        "# LeWM Overnight Report",
        "",
        f"- started: {preflight['started']}",
        f"- device: {preflight['device']}",
        f"- cuda_available: {preflight['cuda_available']}",
        f"- wandb_enabled: {preflight['wandb_enabled']}",
        "",
        "## Data",
    ]
    for name, manifest in preflight["data"].items():
        lines.append(f"- {name}: {manifest['sessions']} sessions, {manifest['frames']} synced frames")
        for d in manifest["domains"]:
            lines.append(f"  - {d['domain']} `{d['path']}`: {d['sessions']} sessions, {d['frames']} frames")
    lines += ["", "## Results"]
    if not results:
        lines.append("- no experiments completed yet")
    for r in results:
        status = r.get("status", "unknown")
        lines.append(f"- {r['name']} [{status}]")
        if "summary" in r:
            s = r["summary"]
            lines.append(
                f"  - val_pred={s.get('best_val_pred', float('nan')):.4f}, "
                f"rollout1_ratio={s.get('rollout1_ratio', float('nan')):.3f}, "
                f"eff_rank={s.get('eff_rank', float('nan')):.1f}, "
                f"steer_sens={s.get('act_steer_sens', float('nan')):.4f}"
            )
        if "cem" in r:
            c = r["cem"]
            if "error" in c:
                lines.append(f"  - CEM dry-run error: {c['error'][:240]}")
            else:
                lines.append(
                    f"  - CEM score={c.get('cem_score', float('nan')):.4f}, "
                    f"vs random_mean={c.get('cem_vs_random_mean', float('nan')):.3f}, "
                    f"vs teacher={c.get('cem_vs_teacher', float('nan')):.3f}"
                )
        if "error" in r:
            lines.append(f"  - error: {r['error'][:300]}")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")


def make_cfg(base: dict, exp_name: str, stage_name: str, overrides: dict, run_dir: Path,
             device: str, wandb_enabled: bool) -> dict:
    cfg = apply_overrides(base, COMMON)
    cfg = apply_overrides(cfg, overrides)
    cfg["device"] = device
    cfg["kfold"] = int(cfg.get("kfold", 0) or 0)
    cfg["model"]["num_frames"] = cfg["data"]["seq_len"]
    cfg["train"]["out_dir"] = str(Path("checkpoints") / "overnight" / exp_name / stage_name)
    cfg.setdefault("wandb", {})["enabled"] = wandb_enabled
    cfg["wandb"]["group"] = f"lewm_overnight_{run_dir.name}"
    cfg["wandb"]["name_override"] = f"{exp_name}/{stage_name}"
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-experiments", type=int, default=None)
    ap.add_argument("--allow-cpu", action="store_true")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--wandb", action="store_true", help="Force W&B on. Default: on only when WANDB_API_KEY is set.")
    ap.add_argument("--dry-run", action="store_true", help="Write manifest/plan without training.")
    ap.add_argument("--cem-cases", type=int, default=12)
    ap.add_argument("--cem-horizon", type=int, default=6)
    args = ap.parse_args()

    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("runs") / "lewm_overnight" / started
    run_dir.mkdir(parents=True, exist_ok=True)
    base = load_config("configs/train/lewm.yaml", "configs/model/leworldmodel.yaml")

    cuda = torch.cuda.is_available()
    device = "cuda" if args.device == "auto" and cuda else args.device
    if device == "auto":
        device = "cpu"
    wandb_enabled = bool(args.wandb or os.environ.get("WANDB_API_KEY"))
    preflight = {
        "started": started,
        "device": device,
        "cuda_available": cuda,
        "wandb_enabled": wandb_enabled,
        "data": {
            "towerpro": data_manifest([{"path": "data/raw_towerpro", "domain": "towerpro", "domain_id": 0}]),
            "kds680hv": data_manifest([{"path": "data/raw", "domain": "kds680hv", "domain_id": 0}]),
            "mixed": data_manifest([
                {"path": "data/raw", "domain": "kds680hv", "domain_id": 0},
                {"path": "data/raw_towerpro", "domain": "towerpro", "domain_id": 1},
            ]),
        },
        "experiments": EXPERIMENTS,
    }
    (run_dir / "manifest.json").write_text(json.dumps(json_safe(preflight), indent=2))

    results: list[dict] = []
    write_report(run_dir, results, preflight)
    if args.dry_run:
        print(f"[dry-run] wrote {run_dir / 'manifest.json'} and {run_dir / 'report.md'}")
        return
    if device == "cpu" and not args.allow_cpu:
        results.append({"name": "preflight", "status": "blocked", "error": "CUDA is not available; refusing overnight CPU training."})
        (run_dir / "results.json").write_text(json.dumps(json_safe(results), indent=2))
        write_report(run_dir, results, preflight)
        print(f"[blocked] CUDA unavailable. Report: {run_dir / 'report.md'}")
        return

    exps = EXPERIMENTS[:args.max_experiments] if args.max_experiments else EXPERIMENTS
    for exp in exps:
        exp_name = exp["name"]
        stages = exp.get("stages") or [{"suffix": "full", "set": exp.get("set", {})}]
        previous_ckpt = None
        final_result = {"name": exp_name, "status": "running", "stages": []}
        results.append(final_result)
        write_report(run_dir, results, preflight)
        for stage in stages:
            suffix = stage["suffix"]
            overrides = dict(stage.get("set", {}))
            if stage.get("init_from_previous") and previous_ckpt:
                overrides["train.init_from"] = str(previous_ckpt)
            cfg = make_cfg(base, exp_name, suffix, overrides, run_dir, device, wandb_enabled)
            out_dir = Path(cfg["train"]["out_dir"])
            print(f"\n########## {exp_name}/{suffix} ##########", flush=True)
            t0 = time.time()
            stage_result = {"stage": suffix, "out_dir": str(out_dir), "status": "running"}
            final_result["stages"].append(stage_result)
            try:
                summary = train(cfg)
                ckpt = checkpoint_path(out_dir)
                previous_ckpt = ckpt
                cem = run_cem_dryrun(ckpt, run_dir / f"cem_{exp_name}_{suffix}.json", args.cem_cases, args.cem_horizon)
                stage_result.update({
                    "status": "complete",
                    "minutes": round((time.time() - t0) / 60, 1),
                    "checkpoint": str(ckpt),
                    "summary": summary,
                    "cem": cem,
                })
                final_result["summary"] = summary
                final_result["cem"] = cem
                final_result["checkpoint"] = str(ckpt)
                torch.cuda.empty_cache()
            except Exception as e:
                stage_result.update({"status": "error", "error": repr(e)})
                final_result.update({"status": "error", "error": repr(e)})
                break
            finally:
                (run_dir / "results.json").write_text(json.dumps(json_safe(results), indent=2))
                write_report(run_dir, results, preflight)
        if final_result.get("status") != "error":
            final_result["status"] = "complete"
            (run_dir / "results.json").write_text(json.dumps(json_safe(results), indent=2))
            write_report(run_dir, results, preflight)

    print(f"\nDone. Report: {run_dir / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
