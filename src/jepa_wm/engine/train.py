"""Training loop for the frozen-V-JEPA Action-Conditioned predictor (vjepa_ac).

Loads pre-encoded latents (engine.encode -> data/latents/), trains the small
ACPredictor with MSE+cosine, AdamW+cosine schedule, early stopping, wandb, and a
final offline eval (multi-step rollout MSE vs an identity baseline). Latents are
z-scored using train-split statistics (saved in the checkpoint for inference).

Entry: scripts/train.py.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from ..data import LatentTransitionDataset
from ..data.dataset import list_sessions, split_sessions
from ..models import build_model
from .losses import ac_loss

try:
    import wandb
except Exception:  # pragma: no cover
    wandb = None


def _sessions_with_latents(latents_dir):
    return sorted(p.stem for p in Path(latents_dir).glob("*.pt"))


def _standardizer(ds: LatentTransitionDataset, device):
    allz = torch.cat([v for v in ds._lat.values()])           # (N, D)
    mean, std = allz.mean(0), allz.std(0).clamp_min(1e-6)
    return mean.to(device), std.to(device)


def _cosine_warmup(step, total, warmup, base_lr):
    if step < warmup:
        return base_lr * (step + 1) / max(1, warmup)
    prog = (step - warmup) / max(1, total - warmup)
    return 0.5 * base_lr * (1 + math.cos(math.pi * min(1.0, prog)))


@torch.no_grad()
def final_eval(model, ds_eval, device, mean, std, horizon, max_n=4000):
    """Multi-step rollout MSE (model vs identity) on z-scored latents."""
    model.eval()
    mod, idn = {}, {}
    n = min(len(ds_eval), max_n)
    for i in range(n):
        item = ds_eval[i]
        lat = ((item["latents"].to(device) - mean) / std)     # (H+1, D)
        acts = item["actions"].to(device)                     # (H, A)
        s = lat[0:1]
        preds = model.rollout(s, acts.unsqueeze(0))[0]        # (H, D)
        for k in range(horizon):
            mod.setdefault(k + 1, []).append(F.mse_loss(preds[k], lat[k + 1]).item())
            idn.setdefault(k + 1, []).append(F.mse_loss(lat[0], lat[k + 1]).item())
    return ({k: float(np.mean(v)) for k, v in mod.items()},
            {k: float(np.mean(v)) for k, v in idn.items()})


def train(cfg: dict) -> dict:
    device = cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(cfg.get("seed", 0))
    d, tcfg = cfg["data"], cfg["train"]
    lat_dir = d["latents_dir"]

    sessions = _sessions_with_latents(lat_dir)
    if not sessions:
        raise RuntimeError(f"No latents in {lat_dir}. Run scripts/encode_dataset.py first.")
    train_s, val_s = split_sessions(sessions, val_frac=d.get("val_frac", 0.2), seed=cfg.get("seed", 0))
    print(f"[vjepa_ac] {len(sessions)} sessions -> {len(train_s)} train / {len(val_s)} val")

    ascale = d.get("action_scale")
    train_ds = LatentTransitionDataset(lat_dir, d["raw_dir"], sessions=train_s, horizon=1, action_scale=ascale)
    val_ds = LatentTransitionDataset(lat_dir, d["raw_dir"], sessions=val_s, horizon=1, action_scale=ascale)
    eval_ds = LatentTransitionDataset(lat_dir, d["raw_dir"], sessions=val_s, action_scale=ascale,
                                      horizon=cfg.get("eval", {}).get("horizon", 10))
    mean, std = _standardizer(train_ds, device)

    bs = tcfg["batch_size"]
    train_dl = DataLoader(train_ds, batch_size=bs, shuffle=True, num_workers=tcfg.get("num_workers", 6),
                          drop_last=True, pin_memory=True)
    val_dl = DataLoader(val_ds, batch_size=bs, shuffle=False, num_workers=tcfg.get("num_workers", 6))
    print(f"[vjepa_ac] windows: {len(train_ds)} train / {len(val_ds)} val / {len(eval_ds)} eval")

    model = build_model(cfg["model"]).to(device)
    print(f"[vjepa_ac] {sum(p.numel() for p in model.parameters())/1e6:.2f}M params")
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg.get("weight_decay", 1e-4))
    total_steps = tcfg["epochs"] * len(train_dl)
    warmup = int(tcfg.get("warmup_frac", 0.05) * total_steps)
    cos_w = tcfg.get("cos_weight", 0.5)

    out_dir = Path(tcfg.get("out_dir", "checkpoints")) / "vjepa_ac"
    out_dir.mkdir(parents=True, exist_ok=True)
    wcfg = cfg.get("wandb", {})
    run = wandb.init(project=wcfg.get("project", "lewm-rccar"), entity=wcfg.get("entity"),
                     group=wcfg.get("group", "vjepa_ac"), name="vjepa_ac", config=cfg,
                     reinit="finish_previous") if wcfg.get("enabled", False) and wandb else None

    best, best_ep, since, gstep = float("inf"), -1, 0, 0
    for epoch in range(tcfg["epochs"]):
        model.train(); t0 = time.time(); tl = 0.0
        for b in train_dl:
            lr = _cosine_warmup(gstep, total_steps, warmup, tcfg["lr"])
            for g in opt.param_groups:
                g["lr"] = lr
            s_t = ((b["s_t"].to(device) - mean) / std)
            s_n = ((b["s_next"].to(device) - mean) / std)
            a_t = b["a_t"].to(device)
            opt.zero_grad(set_to_none=True)
            pred = model(s_t, a_t)
            loss, parts = ac_loss(pred, s_n, cos_weight=cos_w)
            loss.backward(); opt.step()
            tl += loss.item()
            if run and gstep % 50 == 0:
                run.log({"train/loss": loss.item(), "train/mse": parts["mse"].item(),
                         "train/cos": parts["cos"].item(), "train/lr": lr}, step=gstep)
            gstep += 1

        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in val_dl:
                s_t = ((b["s_t"].to(device) - mean) / std); s_n = ((b["s_next"].to(device) - mean) / std)
                pred = model(s_t, b["a_t"].to(device))
                loss, _ = ac_loss(pred, s_n, cos_weight=cos_w)
                vl += loss.item()
        vl /= max(1, len(val_dl))
        if run:
            run.log({"val/loss": vl, "epoch": epoch}, step=gstep)
        print(f"[vjepa_ac] ep {epoch:3d} | train {tl/len(train_dl):.4f} | val {vl:.4f} | {time.time()-t0:.0f}s", flush=True)

        ckpt = {"epoch": epoch, "model": model.state_dict(), "cfg": cfg, "val": vl,
                "lat_mean": mean.cpu(), "lat_std": std.cpu()}
        torch.save(ckpt, out_dir / "last.pt")
        if vl < best - tcfg.get("min_delta", 0.0):
            best, best_ep, since = vl, epoch, 0
            torch.save(ckpt, out_dir / "best.pt")
        else:
            since += 1
            if since >= tcfg.get("patience", 15):
                print(f"[vjepa_ac] early-stop (best {best:.4f} @ ep {best_ep})", flush=True)
                break

    model.load_state_dict(torch.load(out_dir / "best.pt", map_location=device)["model"])
    H = cfg.get("eval", {}).get("horizon", 10)
    mod, idn = final_eval(model, eval_ds, device, mean, std, H)
    ratio1 = mod[1] / max(idn[1], 1e-9)
    print(f"[vjepa_ac] DONE best_val {best:.4f} | rollout@1 {mod[1]:.4f} (×identity {ratio1:.2f}) "
          f"| rollout@{H} {mod[H]:.4f}", flush=True)
    if run:
        run.summary["final/best_val"] = best
        run.summary["final/rollout1"] = mod[1]
        run.summary["final/rollout1_ratio"] = ratio1
        run.finish()
    return {"best_val": best, "rollout1": mod[1], "rollout1_ratio": ratio1}
