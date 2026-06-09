#!/usr/bin/env python3
"""Train the GoalPolicyPrior (PiJEPA-style CEM warm-start) by behavior cloning.

Reads everything from the world-model checkpoint so train/inference stay consistent:
data roots + frozen split.json (same train/val sessions), state columns + z-score stats.
Inputs are the POOLED 384 latents (data/latents_towerpro + data/latents_kds — derive
them from the patch cache with scripts/pool_patch_latents.py, no GPU needed).

Sample = (z_t, z_{t+d*stride}, state_t, domain) -> human action_t, with d ~ U{1..d_max}
(so the policy learns goal-reaching at the same distances the CEM evaluates: d=1..8).
Loss = L1 with throttle up-weighted 6.67x (same balance as the world model action_scale).

Runs fine on CPU (~1.6M params) — the GPU stays free for the world-model training.

    PYTHONPATH=src python scripts/train_policy_prior.py            # defaults
    # then: eval_goal_reaching_ac.py --policy checkpoints/policy_prior/best.pt
    #       inference_loop.py        --policy checkpoints/policy_prior/best.pt
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from jepa_wm.data.dataset import frozen_split
from jepa_wm.data.state import load_state
from jepa_wm.models.policy_prior import GoalPolicyPrior, pooled_dir_for


def load_split_and_roots(ckpt):
    cfg = ckpt["cfg"]
    d = cfg["data"]
    roots = d.get("roots") or [{"patch_dir": d["patch_dir"], "raw_dir": d["raw_dir"], "domain_id": 0}]
    for r in roots:
        r["pooled_dir"] = pooled_dir_for(r["raw_dir"])
        r["_sessions"] = sorted(p.stem for p in Path(r["pooled_dir"]).glob("*.pt"))
    sessions = sorted(s for r in roots for s in r["_sessions"])
    return cfg, roots, sessions


class PolicyDataset(torch.utils.data.Dataset):
    """All pooled latents/states in RAM (~1 GB). d resampled per __getitem__."""

    def __init__(self, roots, sessions, cols, state_mean, state_std, stride=2, d_max=8, seed=0):
        self.stride, self.d_max = stride, d_max
        self.rng = np.random.default_rng(seed)
        self.Z, self.S, self.A, self.D = [], [], [], []   # per-session arrays
        self.anchors = []                                  # (sess_pos, row)
        want = set(sessions)
        for r in roots:
            dom = float(r.get("domain_id", 0))
            for s in r["_sessions"]:
                if s not in want:
                    continue
                blob = torch.load(Path(r["pooled_dir"]) / f"{s}.pt", map_location="cpu", weights_only=False)
                z = blob["latents"].float()
                st, fidx = load_state(Path(r["raw_dir"]) / s, cols)
                assert len(fidx) == z.shape[0], f"pooled/state row mismatch in {s}"
                import csv
                with open(Path(r["raw_dir"]) / s / "actions_synced.csv") as f:
                    act = np.array([[float(row["steering"]), float(row["throttle"])]
                                    for row in csv.DictReader(f)], dtype=np.float32)
                st = (torch.from_numpy(st) - state_mean) / state_std
                pos = len(self.Z)
                self.Z.append(z); self.S.append(st.float())
                self.A.append(torch.from_numpy(act)); self.D.append(dom)
                n = z.shape[0]
                span_min = self.stride            # need at least d=1 ahead
                for i in range(n - span_min):
                    self.anchors.append((pos, i))

    def __len__(self):
        return len(self.anchors)

    def __getitem__(self, k):
        pos, i = self.anchors[k]
        n = self.Z[pos].shape[0]
        d_hi = min(self.d_max, (n - 1 - i) // self.stride)
        d = int(self.rng.integers(1, d_hi + 1))
        j = i + d * self.stride
        return {"z": self.Z[pos][i], "zg": self.Z[pos][j], "s": self.S[pos][i],
                "dom": torch.tensor(self.D[pos]), "a": self.A[pos][i]}

    def fixed_pairs(self, d, max_n=2000, seed=0):
        """Deterministic (z, zg, s, dom, a) batch at one exact goal distance d (for val)."""
        rng = np.random.default_rng(seed)
        ok = [(p, i) for p, i in self.anchors if i + d * self.stride < self.Z[p].shape[0]]
        if not ok:
            return None
        sel = [ok[t] for t in rng.choice(len(ok), size=min(max_n, len(ok)), replace=False)]
        z = torch.stack([self.Z[p][i] for p, i in sel])
        zg = torch.stack([self.Z[p][i + d * self.stride] for p, i in sel])
        s = torch.stack([self.S[p][i] for p, i in sel])
        dom = torch.tensor([self.D[p] for p, _ in sel])
        a = torch.stack([self.A[p][i] for p, i in sel])
        return z, zg, s, dom, a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt",
                    help="world-model ckpt (for roots/split/state-stats)")
    ap.add_argument("--out-dir", default="checkpoints/policy_prior")
    ap.add_argument("--d-max", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--device", default="cpu", help="cpu by default — GPU is busy training the WM")
    ap.add_argument("--num-workers", type=int, default=4)
    args = ap.parse_args()
    torch.manual_seed(0)

    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    cfg, roots, sessions = load_split_and_roots(ckpt)
    d_ = cfg["data"]
    cols = tuple(d_["state_columns"])
    stride = d_.get("frame_stride", 2)
    sm, ss = ckpt["state_mean"].float(), ckpt["state_std"].float()
    use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)

    split_path = Path(args.checkpoint).parent / "split.json"
    train_s, val_s, sinfo = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                         seed=cfg.get("seed", 0), save=False)
    print(f"[policy] {len(sessions)} pooled sessions -> {len(train_s)} train / {len(val_s)} val "
          f"({'FROZEN' if sinfo['frozen'] else 'deterministic'}) | state {cols} | stride {stride} "
          f"| d_max {args.d_max} | domain={'on' if use_domain else 'off'}")

    t0 = time.time()
    tr = PolicyDataset(roots, train_s, cols, sm, ss, stride, args.d_max, seed=0)
    va = PolicyDataset(roots, val_s, cols, sm, ss, stride, args.d_max, seed=1)
    print(f"[policy] anchors: {len(tr)} train / {len(va)} val (loaded in {time.time()-t0:.0f}s)")

    model = GoalPolicyPrior(latent_dim=tr.Z[0].shape[1], state_dim=len(cols),
                            hidden=args.hidden, depth=args.depth, use_domain=use_domain).to(args.device)
    print(f"[policy] {sum(p.numel() for p in model.parameters())/1e6:.2f}M params on {args.device}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    w = torch.tensor([1.0, 6.67], device=args.device)        # throttle up-weight (= action_scale)
    dl = torch.utils.data.DataLoader(tr, batch_size=args.batch_size, shuffle=True,
                                     num_workers=args.num_workers, drop_last=True)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    def run_val():
        model.eval(); tot, n = 0.0, 0
        with torch.no_grad():
            for d in (1, 2, 4, 8):
                pairs = va.fixed_pairs(min(d, args.d_max), max_n=1500)
                if pairs is None:
                    continue
                z, zg, s, dom, a = (t.to(args.device) for t in pairs)
                pred = model(z, zg, s, dom if use_domain else None)
                tot += F.l1_loss(pred * w, a * w, reduction="sum").item(); n += a.numel()
        return tot / max(n, 1)

    best, since = float("inf"), 0
    for ep in range(args.epochs):
        model.train(); tl, t0 = 0.0, time.time()
        for b in dl:
            z, zg, s, a = (b[k].to(args.device) for k in ("z", "zg", "s", "a"))
            dom = b["dom"].to(args.device) if use_domain else None
            loss = F.l1_loss(model(z, zg, s, dom) * w, a * w)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
            tl += loss.item()
        sched.step()
        vl = run_val()
        print(f"[policy] ep {ep:3d} | train {tl/max(len(dl),1):.4f} | val(w-L1) {vl:.4f} | {time.time()-t0:.0f}s", flush=True)
        ck = {"model": model.state_dict(), "val": vl,
              "meta": {"latent_dim": tr.Z[0].shape[1], "state_dim": len(cols), "hidden": args.hidden,
                       "depth": args.depth, "use_domain": use_domain, "state_columns": list(cols),
                       "frame_stride": stride, "d_max": args.d_max,
                       "state_mean": sm, "state_std": ss, "wm_checkpoint": args.checkpoint}}
        torch.save(ck, out_dir / "last.pt")
        if vl < best - 1e-4:
            best, since = vl, 0
            torch.save(ck, out_dir / "best.pt")
        else:
            since += 1
            if since >= args.patience:
                print(f"[policy] early-stop (best {best:.4f})", flush=True)
                break

    # final per-d action-recovery report (RAW units — directly comparable with the CEM table)
    model.load_state_dict(torch.load(out_dir / "best.pt", map_location=args.device, weights_only=False)["model"])
    model.eval()
    print(f"\n{'d':>3} {'med|Δsteer|':>11} {'med|Δthrot|':>11}   (policy alone, val, RAW)")
    with torch.no_grad():
        for d in (1, 2, 4, 8):
            pairs = va.fixed_pairs(min(d, args.d_max), max_n=1500)
            if pairs is None:
                continue
            z, zg, s, dom, a = (t.to(args.device) for t in pairs)
            pred = model(z, zg, s, dom if use_domain else None)
            err = (pred - a).abs().median(dim=0).values
            print(f"{d:>3} {float(err[0]):>11.3f} {float(err[1]):>11.3f}")
    print(f"[policy] DONE best val(w-L1) {best:.4f} -> {out_dir}/best.pt")


if __name__ == "__main__":
    main()
