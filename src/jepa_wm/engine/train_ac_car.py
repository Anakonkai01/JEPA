"""Training loop for VJEPA2ACCar — the faithful V-JEPA-2-AC car controller.

Patch-token AC predictor on frozen V-JEPA 2.1 features. Objective = L1 teacher-forcing
+ 2-step rollout (V-JEPA 2 paper eq. 2-4). Patch tokens z-scored per-dim (stats sampled
from a few train sessions, since the full cache is ~66 GB); state z-scored too. Stats
saved in the checkpoint for inference (planning).

Entry: scripts/train_ac_car.py.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from ..data.ac_clip import ACClipDataset, SessionBatchSampler
from ..data.dataset import frozen_split
from ..data.state import load_state
from ..models import build_model

try:
    import wandb
except Exception:  # pragma: no cover
    wandb = None


def _state_stats(roots, cols):
    """Compute state mean/std from train sessions across all roots.

    roots: list of {'raw_dir': str, 'sessions': list[str]}
    """
    xs = []
    for rc in roots:
        r_dir = Path(rc["raw_dir"])
        for s in rc.get("sessions", []):
            try:
                st, _ = load_state(r_dir / s, cols)
                xs.append(torch.from_numpy(st))
            except Exception:
                pass
    x = torch.cat(xs).float()
    return x.mean(0), x.std(0).clamp_min(1e-6)


def _cosine_warmup(step, total, warmup, base_lr):
    if step < warmup:
        return base_lr * (step + 1) / max(1, warmup)
    prog = (step - warmup) / max(1, total - warmup)
    return 0.5 * base_lr * (1 + math.cos(math.pi * min(1.0, prog)))


def _losses(model, b, device):
    """L1 teacher-forcing + 2-step rollout (grad through one recurrent step)."""
    z = b["tokens"].to(device); a = b["actions"].to(device); s = b["states"].to(device)
    out = model(z, a, s)                                        # (B,T,N,D)
    tf = F.l1_loss(out[:, :-1], z[:, 1:])
    # 2-step rollout: predict z[:,1] from z[:,:1], feed back, predict z[:,2]
    if z.size(1) >= 3:
        p1 = model(z[:, :1], a[:, :1], s[:, :1])[:, -1:]        # ẑ1
        p1 = F.layer_norm(p1, (p1.size(-1),))                   # re-LN fed-back rep (= rollout())
        ctx = torch.cat([z[:, :1], p1], dim=1)                  # (B,2,N,D)
        p2 = model(ctx, a[:, :2], s[:, :2])[:, -1:]             # ẑ2
        ro = F.l1_loss(p2[:, 0], z[:, 2])
    else:
        ro = torch.zeros((), device=device)
    return tf + ro, tf.detach(), ro.detach()


@torch.no_grad()
def final_eval(model, ds, device, horizon, max_n=2000):
    """Rollout L1 (model vs identity) at each step, on z-scored patch tokens."""
    model.eval()
    mod, idn = {}, {}
    n = min(len(ds), max_n)
    idx = np.linspace(0, len(ds) - 1, n).astype(int)
    for i in idx:
        b = ds[int(i)]
        z = b["tokens"].unsqueeze(0).to(device); a = b["actions"].unsqueeze(0).to(device)
        s = b["states"].unsqueeze(0).to(device)
        T = z.size(1)
        preds = model.rollout(z[:, :1], s, a, history=2)        # (1, T-1, N, D)
        for k in range(min(horizon, T - 1)):
            mod.setdefault(k + 1, []).append(F.l1_loss(preds[0, k], z[0, k + 1]).item())
            idn.setdefault(k + 1, []).append(F.l1_loss(z[0, 0], z[0, k + 1]).item())
    return ({k: float(np.mean(v)) for k, v in mod.items()},
            {k: float(np.mean(v)) for k, v in idn.items()})


def train(cfg: dict) -> dict:
    device = cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(cfg.get("seed", 0))
    d, tcfg = cfg["data"], cfg["train"]
    cols = tuple(d.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    T, stride = d.get("horizon", 4), d.get("frame_stride", 2)
    ascale = tuple(d.get("action_scale", [1.0, 6.67]))

    out_dir = Path(tcfg.get("out_dir", "checkpoints/vjepa_ac_car")) / "vjepa_ac_car"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Support multi-root config (roots: list of {patch_dir, raw_dir, domain_id}).
    # Falls back to legacy single-root (patch_dir / raw_dir) when 'roots' is absent.
    raw_roots = d.get("roots")
    if raw_roots is None:
        raw_roots = [{"patch_dir": d["patch_dir"], "raw_dir": d["raw_dir"], "domain_id": 0}]
    use_domain = len(raw_roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in raw_roots)

    # Discover sessions per root (what's actually encoded on disk)
    for r in raw_roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    all_sessions = sorted(s for r in raw_roots for s in r["_sessions"])
    if not all_sessions:
        raise RuntimeError("No patch latents found in any configured root. Run encode_patch.py first.")

    # Reproducible split frozen to out_dir/split.json (saved on first run, reused after).
    train_s, val_s, sinfo = frozen_split(out_dir / "split.json", all_sessions,
                                         val_frac=d.get("val_frac", 0.2), seed=cfg.get("seed", 0))
    tag = "FROZEN <- split.json" if sinfo["frozen"] else f"saved -> {sinfo['path']}"
    print(f"[ac_car] {len(all_sessions)} sessions -> {len(train_s)} train / {len(val_s)} val ({tag})")
    if sinfo["missing"]:
        print(f"[ac_car]   ⚠️ {len(sinfo['missing'])} session(s) in split.json no longer on disk (skipped)")
    if sinfo["extra"]:
        print(f"[ac_car]   ⚠️ {len(sinfo['extra'])} NEW session(s) not in split.json -> unused "
              f"(delete {sinfo['path']} to regenerate the split)")

    # per-root balance report
    train_set, val_set = set(train_s), set(val_s)
    for r in raw_roots:
        r_train = [s for s in r["_sessions"] if s in train_set]
        r_val = [s for s in r["_sessions"] if s in val_set]
        r["_train"] = r_train; r["_val"] = r_val
        tag_d = f"domain_id={r.get('domain_id', 0)}"
        print(f"[ac_car]   {Path(r['patch_dir']).name} ({tag_d}): {len(r_train)} train / {len(r_val)} val")

    # state stats from all train sessions across all roots
    train_roots_stat = [{"raw_dir": r["raw_dir"], "sessions": r["_train"]} for r in raw_roots]
    state_mean, state_std = _state_stats(train_roots_stat, cols)

    # build datasets — multi-root uses domain token in action (action_dim increases by 1)
    if use_domain:
        train_roots_ds = [{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                           "sessions": r["_train"], "domain_id": r.get("domain_id", 0)}
                          for r in raw_roots]
        val_roots_ds = [{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                         "sessions": r["_val"], "domain_id": r.get("domain_id", 0)}
                        for r in raw_roots]
        kw = dict(horizon=T, frame_stride=stride, state_columns=cols, action_scale=ascale,
                  state_mean=state_mean, state_std=state_std, max_gap=d.get("max_gap"))
        train_ds = ACClipDataset(roots=train_roots_ds, **kw)
        val_ds = ACClipDataset(roots=val_roots_ds, **kw)
    else:
        r0 = raw_roots[0]
        kw = dict(horizon=T, frame_stride=stride, state_columns=cols, action_scale=ascale,
                  state_mean=state_mean, state_std=state_std, max_gap=d.get("max_gap"))
        train_ds = ACClipDataset(r0["patch_dir"], r0["raw_dir"], r0["_train"], **kw)
        val_ds = ACClipDataset(r0["patch_dir"], r0["raw_dir"], r0["_val"], **kw)
    print(f"[ac_car] windows: {len(train_ds)} train / {len(val_ds)} val | state {cols}")

    bs = tcfg["batch_size"]
    nw = tcfg.get("num_workers", 4)
    train_sampler = SessionBatchSampler(train_ds.index, bs, shuffle=True, drop_last=True, seed=cfg.get("seed", 0))
    val_sampler = SessionBatchSampler(val_ds.index, bs, shuffle=False, drop_last=False)
    train_dl = DataLoader(train_ds, batch_sampler=train_sampler, num_workers=nw, pin_memory=True)
    val_dl = DataLoader(val_ds, batch_sampler=val_sampler, num_workers=nw)

    model = build_model(cfg["model"]).to(device)
    print(f"[ac_car] {sum(p.numel() for p in model.parameters())/1e6:.2f}M params")
    if tcfg.get("gradient_checkpointing", False) and hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()
        print("[ac_car] gradient checkpointing ON (saves VRAM at ~2x slower backward)")
    if tcfg.get("compile", True) and hasattr(torch, "compile"):
        print("[ac_car] compiling model with torch.compile(default)...")
        model = torch.compile(model, mode="default")
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg.get("weight_decay", 1e-4))
    total_steps = tcfg["epochs"] * len(train_dl)
    warmup = int(tcfg.get("warmup_frac", 0.05) * total_steps)
    use_amp = device.startswith("cuda")

    wcfg = cfg.get("wandb", {})
    run = wandb.init(project=wcfg.get("project", "lewm-rccar"), entity=wcfg.get("entity"),
                     group=wcfg.get("group", "vjepa_ac_car"), name="vjepa_ac_car", config=cfg,
                     reinit="finish_previous") if wcfg.get("enabled", False) and wandb else None

    best, best_ep, since, gstep = float("inf"), -1, 0, 0
    for epoch in range(tcfg["epochs"]):
        train_sampler.set_epoch(epoch)
        model.train(); t0 = time.time(); tl = 0.0
        for b in train_dl:
            lr = _cosine_warmup(gstep, total_steps, warmup, tcfg["lr"])
            for g in opt.param_groups:
                g["lr"] = lr
            opt.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                loss, tf, ro = _losses(model, b, device)
            loss.backward(); opt.step()
            tl += loss.item()
            if run and gstep % 50 == 0:
                run.log({"train/loss": loss.item(), "train/tf": tf.item(), "train/rollout": ro.item(),
                         "train/lr": lr}, step=gstep)
            gstep += 1

        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in val_dl:
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                    loss, _, _ = _losses(model, b, device)
                vl += loss.item()
        vl /= max(1, len(val_dl))
        if run:
            run.log({"val/loss": vl, "epoch": epoch}, step=gstep)
        print(f"[ac_car] ep {epoch:3d} | train {tl/len(train_dl):.4f} | val {vl:.4f} | {time.time()-t0:.0f}s", flush=True)

        ckpt = {"epoch": epoch, "model": model.state_dict(), "cfg": cfg, "val": vl,
                "state_mean": state_mean.cpu(), "state_std": state_std.cpu()}
        torch.save(ckpt, out_dir / "last.pt")
        if vl < best - tcfg.get("min_delta", 0.0):
            best, best_ep, since = vl, epoch, 0
            torch.save(ckpt, out_dir / "best.pt")
        else:
            since += 1
            if since >= tcfg.get("patience", 12):
                print(f"[ac_car] early-stop (best {best:.4f} @ ep {best_ep})", flush=True)
                break

    raw_sd = torch.load(out_dir / "best.pt", map_location=device)["model"]
    sd = {k.replace("_orig_mod.", "", 1): v for k, v in raw_sd.items()}
    model.load_state_dict(sd)
    H = cfg.get("eval", {}).get("horizon", 3)
    mod, idn = final_eval(model, val_ds, device, H)
    ratio1 = mod[1] / max(idn[1], 1e-9)
    print(f"[ac_car] DONE best_val {best:.4f} | rollout@1 {mod[1]:.4f} (×identity {ratio1:.2f})", flush=True)
    if run:
        run.summary.update({"final/best_val": best, "final/rollout1": mod[1], "final/rollout1_ratio": ratio1})
        run.finish()
    return {"best_val": best, "rollout1": mod[1], "rollout1_ratio": ratio1}
