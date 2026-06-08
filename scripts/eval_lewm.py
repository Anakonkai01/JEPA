#!/usr/bin/env python3
"""Thorough offline evaluation of a trained LeWorldModel + a data-coverage report.

    PYTHONPATH=src python scripts/eval_lewm.py --checkpoint checkpoints/leworldmodel/best.pt

Model eval (on the held-out val sessions):
  - multi-step rollout MSE per horizon, vs two trivial baselines:
      * identity  : predict ẑ_{t+1} = z_t  (no change)
      * mean      : predict the global mean latent
    -> normalized error model/identity (<1 means the model beats "no-change").
  - latent geometry: per-dim std, entropy effective-rank, PCA dims for 90/95/99% var.
  - action sensitivity: how much the 1-step prediction changes when the action is
    perturbed (steer flip / throttle bump) -> is the predictor actually using actions?

Data report (all sessions): steering/throttle coverage, forward/reverse/stop &
turn fractions, per-session frame counts. Helps judge if data collection suffices.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from jepa_wm.data import FrameSequenceDataset, list_sessions, normalize_roots, split_sessions
from jepa_wm.models.leworldmodel import LeWorldModel


def _hist(x, bins, lo, hi):
    h, edges = np.histogram(x, bins=bins, range=(lo, hi))
    h = h / max(1, h.sum())
    return "".join(" ▁▂▃▄▅▆▇█"[min(8, int(v * 8 / max(h.max(), 1e-9)))] for v in h)


@torch.no_grad()
def eval_model(model, dl, device, history, emb_dim):
    model.eval()
    horizons = {}
    base_id = {}
    base_mean = {}
    emb_pool = []
    # estimate global mean latent from first batch
    gmean = None
    for bi, batch in enumerate(dl):
        px = batch["pixels"].to(device)
        ac = batch["actions"].to(device)
        z = model.encode(px).float()                 # (B,T,D)
        emb_pool.append(z.reshape(-1, z.size(-1)).cpu())
        if gmean is None:
            gmean = z.mean(dim=(0, 1))
        preds = model.rollout(px[:, :history], ac).float()   # (B, T-H, D)
        gt = z[:, history:]
        n = min(preds.size(1), gt.size(1))
        last_ctx = z[:, history - 1]                 # identity baseline source
        for k in range(n):
            horizons.setdefault(k + 1, []).append(F.mse_loss(preds[:, k], gt[:, k]).item())
            base_id.setdefault(k + 1, []).append(F.mse_loss(last_ctx, gt[:, k]).item())
            base_mean.setdefault(k + 1, []).append(
                F.mse_loss(gmean.expand_as(gt[:, k]), gt[:, k]).item())
    embs = torch.cat(emb_pool)
    # latent geometry
    x = embs - embs.mean(0, keepdim=True)
    std = embs.std(0).mean().item()
    cov = (x.T @ x) / (x.size(0) - 1)
    ev = torch.linalg.eigvalsh(cov).clamp_min(1e-12).flip(0)
    p = ev / ev.sum()
    eff_rank = float(torch.exp(-(p * p.log()).sum()))
    cum = torch.cumsum(p, 0)
    dims = {q: int((cum < q).sum().item()) + 1 for q in (0.90, 0.95, 0.99)}
    return {
        "model": {k: float(np.mean(v)) for k, v in horizons.items()},
        "identity": {k: float(np.mean(v)) for k, v in base_id.items()},
        "mean": {k: float(np.mean(v)) for k, v in base_mean.items()},
        "std": std, "eff_rank": eff_rank, "pca_dims": dims, "emb_dim": emb_dim,
        "n_emb": embs.size(0), "top_eig": ev[:8].tolist(),
    }


@torch.no_grad()
def action_sensitivity(model, dl, device, history):
    """1-step prediction change when the action is perturbed (vs prediction noise floor)."""
    model.eval()
    batch = next(iter(dl))
    px = batch["pixels"].to(device); ac = batch["actions"].to(device)
    z = model.encode(px).float()
    base = model.predict(z[:, :history], model.action_encoder(ac[:, :history])).float()[:, -1]
    variants = {}
    ac2 = ac.clone()
    ac2[..., 0] *= -1.0
    variants["steer_flip"] = ac2
    ac2 = ac.clone()
    ac2[..., 0] = 0.0
    variants["steer_zero"] = ac2
    if ac.size(-1) >= 2:
        ac2 = ac.clone()
        ac2[..., 1] += 0.5
        variants["throttle_+0.5"] = ac2
    out = {}
    for name, ac2 in variants.items():
        p2 = model.predict(z[:, :history], model.action_encoder(ac2[:, :history])).float()[:, -1]
        out[name] = F.mse_loss(p2, base).item()
    return out


def data_report(raw_dir, action_keys=("steering", "throttle")):
    rows = []
    per_sess = {}
    for root in normalize_roots(raw_dir):
        for f in sorted(glob.glob(os.path.join(root.path, "*/actions_synced.csv"))):
            s = f"{root.domain}:{os.path.basename(os.path.dirname(f))}"
            with open(f) as fh:
                r = [(float(x["steering"]), float(x["throttle"])) for x in csv.DictReader(fh)]
            per_sess[s] = len(r); rows += r
    a = np.array(rows); st, th = a[:, 0], a[:, 1]
    return {
        "n_frames": len(a), "n_sessions": len(per_sess),
        "steer": (st.min(), st.max(), st.mean(), st.std()),
        "throt": (th.min(), th.max(), th.mean(), th.std()),
        "steer_hist": _hist(st, 21, -1, 1),
        "throt_hist": _hist(th, 21, -0.15, 0.15),
        "turn_frac": float((np.abs(st) > 0.2).mean()),
        "straight_frac": float((np.abs(st) <= 0.2).mean()),
        "fwd_frac": float((th > 0.02).mean()),
        "rev_frac": float((th < -0.02).mean()),
        "stop_frac": float((np.abs(th) <= 0.02).mean()),
        "sess_min": min(per_sess.values()), "sess_max": max(per_sess.values()),
        "sess_med": int(np.median(list(per_sess.values()))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/leworldmodel/best.pt")
    ap.add_argument("--seq-len", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--max-batches", type=int, default=40)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--raw-dir", nargs="+", default=None)
    ap.add_argument("--domains", nargs="*", default=None,
                    help="keep only val sessions from these domains (e.g. towerpro) — "
                         "reproduces the training split then filters, so it's the honest "
                         "held-out subset for that deployment domain (no re-split leakage).")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    args = ap.parse_args()
    device = args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")

    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    cfg = ckpt["cfg"]; mcfg = cfg["model"]
    model = LeWorldModel(**{k: v for k, v in mcfg.items() if k != "name"}).to(device)
    model.load_state_dict(ckpt["model"])
    print(f"loaded {args.checkpoint} | epoch {ckpt.get('epoch')} | val_pred {ckpt.get('val_pred'):.4f}")

    dcfg = cfg.get("data", {})
    source = args.raw_dir if args.raw_dir else (dcfg.get("raw_dirs") or dcfg.get("raw_dir", "data/raw"))
    if isinstance(source, list) and len(source) == 1 and isinstance(source[0], str):
        source = source[0]
    sessions = list_sessions(source)
    _, val_s = split_sessions(sessions, val_frac=cfg["data"].get("val_frac", 0.2), seed=cfg.get("seed", 0))
    if args.domains:
        val_s = [s for s in val_s if (":" in s and s.split(":")[0] in args.domains)]
        if not val_s:
            raise SystemExit(f"No val sessions in domains {args.domains}. "
                             "(Need a multi-domain checkpoint; single-root ids have no domain prefix.)")
    ds = FrameSequenceDataset(source, sessions=val_s, seq_len=args.seq_len,
                              frame_skip=cfg["data"].get("frame_skip", 1),
                              stride=4, image_size=cfg["data"].get("image_size", 224),
                              action_keys=tuple(cfg["data"].get("action_keys", ("steering", "throttle"))),
                              action_scale=cfg["data"].get("action_scale"),
                              action_aggregation=cfg["data"].get("action_aggregation", "sample"),
                              domain_token=cfg["data"].get("domain_token", "none"))
    # cap batches
    from torch.utils.data import Subset
    idx = list(range(min(len(ds), args.max_batches * args.batch_size)))
    dl = DataLoader(Subset(ds, idx), batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)

    print(f"\nval sessions: {val_s}\nwindows used: {len(idx)} (seq_len {args.seq_len})")

    m = eval_model(model, dl, device, mcfg["history_size"], mcfg["emb_dim"])
    print("\n================ ROLLOUT MSE (lower=better) ================")
    print(f"{'horizon':>8} {'model':>9} {'identity':>9} {'mean':>9} {'model/ident':>12}")
    for k in sorted(m["model"]):
        mo, idn, mn = m["model"][k], m["identity"][k], m["mean"][k]
        print(f"{k:>8} {mo:>9.4f} {idn:>9.4f} {mn:>9.4f} {mo/max(idn,1e-9):>12.2f}")

    print("\n================ LATENT GEOMETRY ================")
    print(f"per-dim std        : {m['std']:.3f}   (≈1 = SIGReg shaping N(0,I); ~0 = collapse)")
    print(f"effective rank     : {m['eff_rank']:.1f} / {m['emb_dim']}   (entropy of eigenspectrum)")
    print(f"PCA dims for var    : 90%={m['pca_dims'][0.90]}  95%={m['pca_dims'][0.95]}  99%={m['pca_dims'][0.99]}  (of {m['emb_dim']})")
    print(f"top-8 eigenvalues  : " + " ".join(f"{e:.2f}" for e in m["top_eig"]))

    s = action_sensitivity(model, dl, device, mcfg["history_size"])
    print("\n================ ACTION SENSITIVITY (1-step pred change) ================")
    print("how much next-latent prediction moves when we perturb the action:")
    for k, v in s.items():
        print(f"  {k:>14}: {v:.4f}")
    print(f"  (compare to model rollout@1 ≈ {m['model'].get(1, float('nan')):.4f}; "
          f"if these are ≪ that, the predictor barely uses actions)")

    d = data_report(source)
    print("\n================ DATA COVERAGE REPORT ================")
    print(f"{d['n_sessions']} sessions, {d['n_frames']} synced frames "
          f"(per-session min/med/max = {d['sess_min']}/{d['sess_med']}/{d['sess_max']})")
    print(f"steering: min {d['steer'][0]:+.2f} max {d['steer'][1]:+.2f} mean {d['steer'][2]:+.3f} std {d['steer'][3]:.3f}")
    print(f"   [-1 {d['steer_hist']} +1]")
    print(f"throttle: min {d['throt'][0]:+.3f} max {d['throt'][1]:+.3f} mean {d['throt'][2]:+.3f} std {d['throt'][3]:.3f}")
    print(f"   [-.15 {d['throt_hist']} +.15]")
    print(f"turn(|steer|>0.2) {d['turn_frac']*100:.0f}%  | straight {d['straight_frac']*100:.0f}%")
    print(f"forward {d['fwd_frac']*100:.0f}%  | reverse {d['rev_frac']*100:.0f}%  | stop {d['stop_frac']*100:.0f}%")


if __name__ == "__main__":
    main()
