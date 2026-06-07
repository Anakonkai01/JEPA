"""End-to-end training for LeWorldModel (pixel JEPA), with k-fold CV + wandb.

Two-term objective (MSE next-embedding + λ·SIGReg), AdamW + cosine warmup, bf16
autocast, early stopping on val prediction loss, wandb logging. Each fold ends
with a full offline evaluation: multi-step rollout MSE vs an identity baseline,
latent geometry (std / effective rank), and action sensitivity. ``kfold`` runs
session-level cross-validation and aggregates mean±std across folds.
See docs/LeWorldModel.md.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from ..data import FrameSequenceDataset, list_sessions
from ..models.leworldmodel import LeWorldModel
from .losses import SIGReg, lewm_loss

try:
    import wandb
except Exception:  # pragma: no cover
    wandb = None


# ─────────────────────────────────────────────────────────── data ───────────
def _mk_ds(cfg, sessions, seq_len):
    d = cfg["data"]
    return FrameSequenceDataset(
        d["raw_dir"], sessions=sessions, seq_len=seq_len, frame_skip=d.get("frame_skip", 1),
        stride=d.get("stride", 2), image_size=d.get("image_size", 224))


def _loaders(cfg, train_s, val_s):
    bs, nw = cfg["train"]["batch_size"], cfg["train"].get("num_workers", 8)
    train_ds, val_ds = _mk_ds(cfg, train_s, cfg["data"]["seq_len"]), _mk_ds(cfg, val_s, cfg["data"]["seq_len"])
    train_dl = DataLoader(train_ds, batch_size=bs, shuffle=True, num_workers=nw, pin_memory=True,
                          drop_last=True, persistent_workers=nw > 0)
    val_dl = DataLoader(val_ds, batch_size=bs, shuffle=False, num_workers=nw, pin_memory=True)
    eval_dl = None
    if cfg.get("eval", {}).get("enabled", True):
        eval_ds = _mk_ds(cfg, val_s, cfg["eval"].get("seq_len", 16))
        eval_dl = DataLoader(eval_ds, batch_size=max(8, bs // 2), shuffle=False, num_workers=nw)
    return train_dl, val_dl, eval_dl


def _cosine_warmup(step, total, warmup, base_lr):
    if step < warmup:
        return base_lr * (step + 1) / max(1, warmup)
    prog = (step - warmup) / max(1, total - warmup)
    return 0.5 * base_lr * (1 + math.cos(math.pi * min(1.0, prog)))


# ─────────────────────────────────────────────────────── final eval ─────────
@torch.no_grad()
def final_eval(model, eval_dl, device, history, emb_dim, max_batches=40):
    """Rollout MSE (model vs identity baseline) + latent geometry + action sensitivity."""
    model.eval()
    mod, idn = {}, {}
    emb_pool = []
    for bi, batch in enumerate(eval_dl):
        if bi >= max_batches:
            break
        px = batch["pixels"].to(device); ac = batch["actions"].to(device)
        z = model.encode(px).float()
        emb_pool.append(z.reshape(-1, z.size(-1)).cpu())
        preds = model.rollout(px[:, :history], ac).float()
        gt = z[:, history:]; ctx = z[:, history - 1]
        for k in range(min(preds.size(1), gt.size(1))):
            mod.setdefault(k + 1, []).append(F.mse_loss(preds[:, k], gt[:, k]).item())
            idn.setdefault(k + 1, []).append(F.mse_loss(ctx, gt[:, k]).item())
    model_mse = {k: float(np.mean(v)) for k, v in mod.items()}
    ident_mse = {k: float(np.mean(v)) for k, v in idn.items()}
    embs = torch.cat(emb_pool)
    x = embs - embs.mean(0, keepdim=True)
    cov = (x.T @ x) / (x.size(0) - 1)
    ev = torch.linalg.eigvalsh(cov).clamp_min(1e-12)
    p = ev / ev.sum()
    eff_rank = float(torch.exp(-(p * p.log()).sum()))
    # action sensitivity (1-step prediction change under perturbed action)
    batch = next(iter(eval_dl))
    px = batch["pixels"].to(device); ac = batch["actions"].to(device)
    z = model.encode(px).float()
    base = model.predict(z[:, :history], model.action_encoder(ac[:, :history])).float()[:, -1]
    ac_flip = ac.clone() * torch.tensor([-1., 1.], device=device)
    flip = model.predict(z[:, :history], model.action_encoder(ac_flip[:, :history])).float()[:, -1]
    steer_sens = F.mse_loss(flip, base).item()
    h1 = max(model_mse)
    return {
        "rollout_model": model_mse, "rollout_identity": ident_mse,
        "rollout1": model_mse[1], "rollout1_ratio": model_mse[1] / max(ident_mse[1], 1e-9),
        "rollout_last": model_mse[h1], "rollout_last_ratio": model_mse[h1] / max(ident_mse[h1], 1e-9),
        "emb_std": embs.std(0).mean().item(), "eff_rank": eff_rank,
        "act_steer_sens": steer_sens, "act_vs_rollout1": steer_sens / max(model_mse[1], 1e-9),
    }


# ─────────────────────────────────────────────────────────── train ──────────
def train(cfg: dict, train_s=None, val_s=None, fold: int | None = None) -> dict:
    device = cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(cfg.get("seed", 0))
    tcfg, scfg = cfg["train"], cfg.get("sigreg", {})
    if train_s is None:
        from ..data import split_sessions
        sess = list_sessions(cfg["data"]["raw_dir"])
        train_s, val_s = split_sessions(sess, val_frac=cfg["data"].get("val_frac", 0.2), seed=cfg.get("seed", 0))

    tag = f"fold{fold}" if fold is not None else "full"
    train_dl, val_dl, eval_dl = _loaders(cfg, train_s, val_s)
    print(f"[{tag}] train {len(train_s)}s/{len(train_dl.dataset)}w | val {len(val_s)}s/{len(val_dl.dataset)}w")

    model = LeWorldModel(**{k: v for k, v in cfg["model"].items() if k != "name"}).to(device)
    sigreg = SIGReg(knots=scfg.get("knots", 17), num_proj=scfg.get("num_proj", 1024)).to(device)
    lambd = scfg.get("lambd", 0.1)
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg.get("weight_decay", 0.05))
    total_steps = tcfg["epochs"] * len(train_dl)
    warmup = int(tcfg.get("warmup_frac", 0.05) * total_steps)
    use_amp = tcfg.get("amp", True) and device.startswith("cuda")

    out_dir = Path(tcfg["out_dir"]) / "leworldmodel" / (tag if fold is not None else "")
    out_dir.mkdir(parents=True, exist_ok=True)

    wcfg = cfg.get("wandb", {})
    run = None
    if wcfg.get("enabled", False) and wandb is not None:
        run = wandb.init(project=wcfg.get("project", "lewm-rccar"), entity=wcfg.get("entity"),
                         group=wcfg.get("group"), name=wcfg.get("name_override", tag), job_type="train",
                         config=cfg, reinit="finish_previous")
        run.summary["n_params_M"] = sum(p.numel() for p in model.parameters()) / 1e6

    best_val, best_epoch, since = float("inf"), -1, 0
    gstep = 0
    for epoch in range(tcfg["epochs"]):
        model.train(); t0 = time.time(); run_l = {"total": 0, "pred": 0, "sig": 0}
        for batch in train_dl:
            lr = _cosine_warmup(gstep, total_steps, warmup, tcfg["lr"])
            for g in opt.param_groups:
                g["lr"] = lr
            px = batch["pixels"].to(device, non_blocking=True)
            ac = batch["actions"].to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                emb, nxt = model(px, ac)
            loss, parts = lewm_loss(emb.float(), nxt.float(), sigreg, lambd=lambd)
            loss.backward()
            if tcfg.get("grad_clip"):
                torch.nn.utils.clip_grad_norm_(model.parameters(), tcfg["grad_clip"])
            opt.step()
            run_l["total"] += loss.item(); run_l["pred"] += parts["pred"].item(); run_l["sig"] += parts["sigreg"].item()
            if run and gstep % 50 == 0:
                run.log({"train/loss": loss.item(), "train/pred": parts["pred"].item(),
                         "train/sigreg": parts["sigreg"].item(), "train/lr": lr}, step=gstep)
            gstep += 1
        nb = len(train_dl)

        model.eval(); vpred = vsig = 0.0
        with torch.no_grad():
            for batch in val_dl:
                emb, nxt = model(batch["pixels"].to(device), batch["actions"].to(device))
                _, parts = lewm_loss(emb.float(), nxt.float(), sigreg, lambd=lambd)
                vpred += parts["pred"].item(); vsig += parts["sigreg"].item()
        nvb = max(1, len(val_dl)); vpred /= nvb; vsig /= nvb
        if run:
            run.log({"val/pred": vpred, "val/sigreg": vsig, "epoch": epoch}, step=gstep)
        print(f"[{tag}] ep {epoch:3d} | train {run_l['total']/nb:.4f} "
              f"(pred {run_l['pred']/nb:.4f} sig {run_l['sig']/nb:.2f}) | val pred {vpred:.4f} | {time.time()-t0:.0f}s",
              flush=True)

        ckpt = {"epoch": epoch, "model": model.state_dict(), "cfg": cfg, "val_pred": vpred}
        torch.save(ckpt, out_dir / "last.pt")
        if vpred < best_val - tcfg.get("min_delta", 0.0):
            best_val, best_epoch, since = vpred, epoch, 0
            torch.save(ckpt, out_dir / "best.pt")
        else:
            since += 1
            if since >= tcfg.get("patience", 15):
                print(f"[{tag}] early-stop (best {best_val:.4f} @ ep {best_epoch})", flush=True)
                break

    # final offline eval on the best checkpoint
    model.load_state_dict(torch.load(out_dir / "best.pt", map_location=device)["model"])
    fe = final_eval(model, eval_dl, device, cfg["model"]["history_size"], cfg["model"]["emb_dim"],
                    max_batches=cfg.get("eval", {}).get("max_batches", 40)) if eval_dl else {}
    summary = {"fold": tag, "best_val_pred": best_val, "best_epoch": best_epoch, **fe}
    print(f"[{tag}] DONE best_val {best_val:.4f} | rollout@1 {fe.get('rollout1', float('nan')):.4f} "
          f"(×identity {fe.get('rollout1_ratio', float('nan')):.2f}) | eff_rank {fe.get('eff_rank', float('nan')):.1f} "
          f"| steer_sens {fe.get('act_steer_sens', float('nan')):.4f}", flush=True)
    if run:
        for k, v in fe.items():
            if isinstance(v, (int, float)):
                run.summary[f"final/{k}"] = v
        run.summary["final/best_val_pred"] = best_val
        run.finish()
    return summary


def _make_folds(sessions, k, seed):
    rng = np.random.default_rng(seed)
    order = list(rng.permutation(len(sessions)))
    return [[sessions[i] for i in order[f::k]] for f in range(k)]   # round-robin folds


def kfold(cfg: dict) -> None:
    k = cfg.get("kfold", 5)
    sessions = list_sessions(cfg["data"]["raw_dir"])
    folds = _make_folds(sessions, k, cfg.get("seed", 0))
    cfg.setdefault("wandb", {}).setdefault("group", f"lewm_fs{cfg['data'].get('frame_skip',1)}_kfold{k}")
    print(f"[kfold] {len(sessions)} sessions -> {k} folds (sizes {[len(f) for f in folds]})")
    results = []
    for fi in range(k):
        val_s = folds[fi]
        train_s = [s for j, f in enumerate(folds) if j != fi for s in f]
        print(f"\n========== FOLD {fi}/{k-1}  val={val_s} ==========")
        results.append(train(cfg, train_s=train_s, val_s=val_s, fold=fi))

    def agg(key):
        xs = [r[key] for r in results if isinstance(r.get(key), (int, float))]
        return (float(np.mean(xs)), float(np.std(xs))) if xs else (float("nan"), 0.0)

    print("\n================ K-FOLD SUMMARY (mean ± std over folds) ================")
    for key in ["best_val_pred", "rollout1", "rollout1_ratio", "rollout_last_ratio",
                "eff_rank", "emb_std", "act_steer_sens"]:
        mu, sd = agg(key)
        print(f"  {key:>20}: {mu:.4f} ± {sd:.4f}")
    print("\nInterpretation: rollout1_ratio < 1 ⇒ model beats no-change baseline; "
          "act_steer_sens ≫ noise ⇒ predictor uses steering; eff_rank ↑ ⇒ richer latent.")
