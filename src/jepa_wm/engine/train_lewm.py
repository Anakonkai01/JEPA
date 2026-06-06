"""End-to-end training loop for LeWorldModel (pixel JEPA).

Two-term objective (MSE next-embedding + λ·SIGReg), AdamW + cosine schedule with
warmup, bf16 autocast, early stopping on val prediction loss, per-epoch
checkpointing + TensorBoard, and an offline evaluation (multi-step rollout MSE +
anti-collapse metrics). See docs/LeWorldModel.md.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from ..data import FrameSequenceDataset, list_sessions, split_sessions
from ..models.leworldmodel import LeWorldModel
from .losses import SIGReg, lewm_loss


# ─────────────────────────────────────────────────────────── helpers ────────
def _build_loaders(cfg):
    d, e = cfg["data"], cfg.get("eval", {})
    sessions = list_sessions(d["raw_dir"])
    train_s, val_s = split_sessions(sessions, val_frac=d.get("val_frac", 0.2),
                                    seed=cfg.get("seed", 0))
    print(f"[data] {len(sessions)} sessions -> {len(train_s)} train / {len(val_s)} val")

    mk = lambda sess, seq: FrameSequenceDataset(
        d["raw_dir"], sessions=sess, seq_len=seq, frame_skip=d.get("frame_skip", 1),
        stride=d.get("stride", 2), image_size=d.get("image_size", 224))
    train_ds = mk(train_s, d["seq_len"])
    val_ds = mk(val_s, d["seq_len"])
    bs, nw = cfg["train"]["batch_size"], cfg["train"].get("num_workers", 8)
    train_dl = DataLoader(train_ds, batch_size=bs, shuffle=True, num_workers=nw,
                          pin_memory=True, drop_last=True, persistent_workers=nw > 0)
    val_dl = DataLoader(val_ds, batch_size=bs, shuffle=False, num_workers=nw, pin_memory=True)

    eval_dl = None
    if e.get("enabled", False):
        eval_ds = mk(val_s, e.get("seq_len", 12))
        eval_dl = DataLoader(eval_ds, batch_size=max(8, bs // 2), shuffle=False, num_workers=nw)
    print(f"[data] windows: {len(train_ds)} train / {len(val_ds)} val"
          + (f" / {len(eval_dl.dataset)} eval-rollout" if eval_dl else ""))
    return train_dl, val_dl, eval_dl


def _cosine_warmup(step, total, warmup, base_lr):
    if step < warmup:
        return base_lr * (step + 1) / max(1, warmup)
    prog = (step - warmup) / max(1, total - warmup)
    return 0.5 * base_lr * (1 + math.cos(math.pi * min(1.0, prog)))


@torch.no_grad()
def _collapse_metrics(embs: torch.Tensor):
    """embs (N, D). Returns (mean per-dim std, effective rank of covariance)."""
    x = embs - embs.mean(0, keepdim=True)
    std = embs.std(0).mean().item()
    cov = (x.T @ x) / max(1, x.size(0) - 1)
    ev = torch.linalg.eigvalsh(cov).clamp_min(1e-12)
    p = ev / ev.sum()
    eff_rank = torch.exp(-(p * p.log()).sum()).item()      # entropy-based effective rank
    return std, eff_rank


@torch.no_grad()
def offline_eval(model, eval_dl, device, history_size, max_batches=20):
    """Multi-step rollout MSE (per horizon) + anti-collapse metrics on val."""
    model.eval()
    per_step, counts = {}, {}
    emb_pool = []
    for bi, batch in enumerate(eval_dl):
        if bi >= max_batches:
            break
        pixels = batch["pixels"].to(device)       # (B, T, C, H, W)
        actions = batch["actions"].to(device)     # (B, T, A)
        T = pixels.size(1)
        gt = model.encode(pixels)                 # (B, T, D)
        emb_pool.append(gt.reshape(-1, gt.size(-1)).float().cpu())
        preds = model.rollout(pixels[:, :history_size], actions)   # (B, T-H, D)
        gt_future = gt[:, history_size:]
        n = min(preds.size(1), gt_future.size(1))
        for k in range(n):
            mse = torch.nn.functional.mse_loss(preds[:, k], gt_future[:, k]).item()
            per_step[k + 1] = per_step.get(k + 1, 0.0) + mse
            counts[k + 1] = counts.get(k + 1, 0) + 1
    rollout = {k: per_step[k] / counts[k] for k in sorted(per_step)}
    std, eff_rank = _collapse_metrics(torch.cat(emb_pool))
    return {"rollout_mse": rollout, "emb_std": std, "eff_rank": eff_rank}


# ─────────────────────────────────────────────────────────── train ──────────
def train(cfg: dict) -> None:
    device = cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(cfg.get("seed", 0))
    tcfg, scfg = cfg["train"], cfg.get("sigreg", {})

    train_dl, val_dl, eval_dl = _build_loaders(cfg)

    model = LeWorldModel(**{k: v for k, v in cfg["model"].items() if k != "name"}).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[model] LeWM {n_params/1e6:.1f}M params | device={device}")
    sigreg = SIGReg(knots=scfg.get("knots", 17), num_proj=scfg.get("num_proj", 1024)).to(device)
    lambd = scfg.get("lambd", 0.1)

    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg.get("weight_decay", 0.05))
    steps_per_epoch = len(train_dl)
    total_steps = tcfg["epochs"] * steps_per_epoch
    warmup = int(tcfg.get("warmup_frac", 0.05) * total_steps)
    use_amp = tcfg.get("amp", True) and device.startswith("cuda")

    out_dir = Path(tcfg["out_dir"]) / "leworldmodel"
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = SummaryWriter(Path(tcfg.get("log_dir", "runs")) / f"lewm_{int(time.time())}")

    best_val, best_epoch, since_improve = float("inf"), -1, 0
    gstep = 0
    for epoch in range(tcfg["epochs"]):
        model.train()
        t0 = time.time()
        run = {"total": 0.0, "pred": 0.0, "sigreg": 0.0}
        for batch in train_dl:
            lr = _cosine_warmup(gstep, total_steps, warmup, tcfg["lr"])
            for g in opt.param_groups:
                g["lr"] = lr
            pixels = batch["pixels"].to(device, non_blocking=True)
            actions = batch["actions"].to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=use_amp):
                emb, next_emb = model(pixels, actions)
            loss, parts = lewm_loss(emb.float(), next_emb.float(), sigreg, lambd=lambd)
            loss.backward()
            if tcfg.get("grad_clip"):
                torch.nn.utils.clip_grad_norm_(model.parameters(), tcfg["grad_clip"])
            opt.step()
            run["total"] += loss.item(); run["pred"] += parts["pred"].item(); run["sigreg"] += parts["sigreg"].item()
            if gstep % 50 == 0:
                writer.add_scalar("train/loss", loss.item(), gstep)
                writer.add_scalar("train/pred", parts["pred"].item(), gstep)
                writer.add_scalar("train/sigreg", parts["sigreg"].item(), gstep)
                writer.add_scalar("train/lr", lr, gstep)
            gstep += 1
        nb = len(train_dl)

        # ---- validation (teacher-forced) ----
        model.eval()
        vpred = vsig = 0.0
        with torch.no_grad():
            for batch in val_dl:
                pixels = batch["pixels"].to(device); actions = batch["actions"].to(device)
                emb, next_emb = model(pixels, actions)
                _, parts = lewm_loss(emb.float(), next_emb.float(), sigreg, lambd=lambd)
                vpred += parts["pred"].item(); vsig += parts["sigreg"].item()
        nvb = max(1, len(val_dl))
        vpred /= nvb; vsig /= nvb
        writer.add_scalar("val/pred", vpred, epoch); writer.add_scalar("val/sigreg", vsig, epoch)

        msg = (f"epoch {epoch:3d} | train loss {run['total']/nb:.4f} "
               f"(pred {run['pred']/nb:.4f} sig {run['sigreg']/nb:.3f}) | "
               f"val pred {vpred:.4f} sig {vsig:.3f} | {time.time()-t0:.0f}s")

        if eval_dl is not None and (epoch % 2 == 0 or epoch == tcfg["epochs"] - 1):
            m = offline_eval(model, eval_dl, device, cfg["model"].get("history_size", 3),
                             max_batches=cfg["eval"].get("max_batches", 20))
            for k, v in m["rollout_mse"].items():
                writer.add_scalar(f"eval/rollout_mse_step{k}", v, epoch)
            writer.add_scalar("eval/emb_std", m["emb_std"], epoch)
            writer.add_scalar("eval/eff_rank", m["eff_rank"], epoch)
            steps = m["rollout_mse"]
            msg += (f" | rollout@1 {steps.get(1, float('nan')):.4f} "
                    f"@{max(steps) if steps else 0} {list(steps.values())[-1] if steps else float('nan'):.4f}"
                    f" | std {m['emb_std']:.3f} effrank {m['eff_rank']:.0f}/{cfg['model']['emb_dim']}")
        print(msg, flush=True)

        # ---- checkpoint + early stopping ----
        ckpt = {"epoch": epoch, "model": model.state_dict(), "cfg": cfg, "val_pred": vpred}
        torch.save(ckpt, out_dir / "last.pt")
        if vpred < best_val - tcfg.get("min_delta", 0.0):
            best_val, best_epoch, since_improve = vpred, epoch, 0
            torch.save(ckpt, out_dir / "best.pt")
            print(f"         ↑ new best val pred {vpred:.4f} (saved best.pt)", flush=True)
        else:
            since_improve += 1
            if since_improve >= tcfg.get("patience", 15):
                print(f"[early-stop] no val improvement for {since_improve} epochs "
                      f"(best {best_val:.4f} @ epoch {best_epoch}).", flush=True)
                break

    writer.close()
    print(f"[done] best val pred {best_val:.4f} @ epoch {best_epoch} -> {out_dir/'best.pt'}")
