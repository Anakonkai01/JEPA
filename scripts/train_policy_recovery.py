#!/usr/bin/env python3
"""Train a RECOVERY-AUGMENTED GoalPolicyPrior (fork of train_policy_prior.py).

Same BC policy pi(pool(z_t), pool(z_goal), state, domain) -> [steer, throttle], but a fraction
``--p-aug`` of training samples replace z_t with a SYNTHETIC LATERAL-OFFSET pooled latent
(scripts/pool_recovery_latents.py: horizontal token-grid shift) and add a CORRECTIVE steer to
the label: shift +s (drift RIGHT) -> steer LEFT by alpha*s/W. Goal stays the on-route future.
→ teaches "I'm off to the side, steer back" — the lateral recovery teach-down-the-middle lacks.

Validation stays on NORMAL (un-augmented) samples so val w-L1 is directly comparable to the
baseline policy_prior_cd4 (recovery shouldn't wreck normal goal-reaching). The decisive test is
scripts/eval_recovery_response.py (does the trained policy produce a GRADED corrective response?).

    PYTHONPATH=src python scripts/train_policy_recovery.py \
        --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
        --out-dir checkpoints/policy_recovery_cd4 --device cpu --epochs 40
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, "scripts")                 # so `train_policy_prior` resolves from repo root
from jepa_wm.data.dataset import frozen_split
from jepa_wm.data.state import load_state
from jepa_wm.models.policy_prior import GoalPolicyPrior, pooled_dir_for
from train_policy_prior import load_split_and_roots


def recovery_dir_for(raw_dir) -> str:
    name = Path(raw_dir).name
    return str(Path(raw_dir).parent / ("latents_" + name.removeprefix("raw_") + "_recovery"))


class RecoveryDataset(torch.utils.data.Dataset):
    """Pooled latents + states + actions + (optional) synthetic-offset aug latents, all in RAM."""

    def __init__(self, roots, sessions, cols, state_mean, state_std, stride, d_max,
                 p_aug, alpha, grid_w, seed=0, train=True):
        self.stride, self.d_max = stride, d_max
        self.p_aug, self.alpha, self.W, self.train = p_aug, alpha, float(grid_w), train
        self.rng = np.random.default_rng(seed)
        self.Z, self.S, self.A, self.D = [], [], [], []
        self.AUG, self.SH = [], []          # per-session (N,n_shifts,D) and shift values
        self.anchors = []
        want = set(sessions)
        for r in roots:
            dom = float(r.get("domain_id", 0))
            rec_dir = Path(recovery_dir_for(r["raw_dir"]))
            for s in r["_sessions"]:
                if s not in want:
                    continue
                blob = torch.load(Path(r["pooled_dir"]) / f"{s}.pt", map_location="cpu", weights_only=False)
                z = blob["latents"].float()
                st, fidx = load_state(Path(r["raw_dir"]) / s, cols)
                assert len(fidx) == z.shape[0], f"pooled/state row mismatch in {s}"
                with open(Path(r["raw_dir"]) / s / "actions_synced.csv") as f:
                    act = np.array([[float(row["steering"]), float(row["throttle"])]
                                    for row in csv.DictReader(f)], dtype=np.float32)
                st = (torch.from_numpy(st) - state_mean) / state_std
                pos = len(self.Z)
                self.Z.append(z); self.S.append(st.float())
                self.A.append(torch.from_numpy(act)); self.D.append(dom)
                if train and (rec_dir / f"{s}.pt").exists():
                    rb = torch.load(rec_dir / f"{s}.pt", map_location="cpu", weights_only=False)
                    aug = rb["aug"].float(); sh = rb["shifts"].tolist()
                    assert aug.shape[0] == z.shape[0], f"recovery rows mismatch {s}"
                    self.AUG.append(aug); self.SH.append(sh)
                else:
                    self.AUG.append(None); self.SH.append(None)
                n = z.shape[0]
                for i in range(n - self.stride):
                    self.anchors.append((pos, i))

    def __len__(self):
        return len(self.anchors)

    def __getitem__(self, k):
        pos, i = self.anchors[k]
        n = self.Z[pos].shape[0]
        d_hi = min(self.d_max, (n - 1 - i) // self.stride)
        d = int(self.rng.integers(1, d_hi + 1))
        j = i + d * self.stride
        z = self.Z[pos][i]
        a = self.A[pos][i].clone()
        if (self.train and self.AUG[pos] is not None and self.p_aug > 0
                and self.rng.random() < self.p_aug):
            ki = int(self.rng.integers(0, self.AUG[pos].shape[1]))
            s = self.SH[pos][ki]
            z = self.AUG[pos][i, ki]                                   # offset view
            a = a.clone()
            a[0] = float(np.clip(float(a[0]) - self.alpha * (s / self.W), -1.0, 1.0))  # steer back
        return {"z": z, "zg": self.Z[pos][j], "s": self.S[pos][i],
                "dom": torch.tensor(self.D[pos]), "a": a}

    def fixed_pairs(self, d, max_n=1500, seed=0):
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
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("--out-dir", default="checkpoints/policy_recovery_cd4")
    ap.add_argument("--p-aug", type=float, default=0.35, help="fraction of train samples = recovery")
    ap.add_argument("--alpha", type=float, default=1.0, help="corrective steer = -alpha*shift/W")
    ap.add_argument("--grid-w", type=int, default=24)
    ap.add_argument("--d-max", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--num-workers", type=int, default=4)
    args = ap.parse_args()
    torch.manual_seed(0)

    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    cfg, roots, sessions = load_split_and_roots(ckpt)
    d_ = cfg["data"]
    cols = tuple(d_["state_columns"]); stride = d_.get("frame_stride", 2)
    sm, ss = ckpt["state_mean"].float(), ckpt["state_std"].float()
    use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)
    split_path = Path(args.checkpoint).parent / "split.json"
    train_s, val_s, sinfo = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                         seed=cfg.get("seed", 0), save=False)
    print(f"[recpol] {len(train_s)} train / {len(val_s)} val ({'FROZEN' if sinfo['frozen'] else 'det'}) "
          f"| p_aug={args.p_aug} alpha={args.alpha} | domain={'on' if use_domain else 'off'}")

    t0 = time.time()
    tr = RecoveryDataset(roots, train_s, cols, sm, ss, stride, args.d_max,
                         args.p_aug, args.alpha, args.grid_w, seed=0, train=True)
    va = RecoveryDataset(roots, val_s, cols, sm, ss, stride, args.d_max,
                         0.0, args.alpha, args.grid_w, seed=1, train=False)
    n_aug = sum(a is not None for a in tr.AUG)
    print(f"[recpol] anchors {len(tr)} train / {len(va)} val | {n_aug}/{len(tr.AUG)} sessions have recovery "
          f"({time.time()-t0:.0f}s)")

    model = GoalPolicyPrior(latent_dim=tr.Z[0].shape[1], state_dim=len(cols),
                            hidden=args.hidden, depth=args.depth, use_domain=use_domain).to(args.device)
    print(f"[recpol] {sum(p.numel() for p in model.parameters())/1e6:.2f}M params on {args.device}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    w = torch.tensor([1.0, 6.67], device=args.device)
    dl = torch.utils.data.DataLoader(tr, batch_size=args.batch_size, shuffle=True,
                                     num_workers=args.num_workers, drop_last=True)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    def run_val():
        model.eval(); tot, n = 0.0, 0
        with torch.no_grad():
            for d in (1, 2, 4, 8):
                pairs = va.fixed_pairs(min(d, args.d_max))
                if pairs is None:
                    continue
                z, zg, s, dom, a = (t.to(args.device) for t in pairs)
                pred = model(z, zg, s, dom if use_domain else None)
                tot += F.l1_loss(pred * w, a * w, reduction="sum").item(); n += a.numel()
        return tot / max(n, 1)

    best, since = float("inf"), 0
    for ep in range(args.epochs):
        model.train(); tl = 0.0; t0 = time.time()
        for b in dl:
            z, zg, s, a = (b[k].to(args.device) for k in ("z", "zg", "s", "a"))
            dom = b["dom"].to(args.device) if use_domain else None
            loss = F.l1_loss(model(z, zg, s, dom) * w, a * w)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
            tl += loss.item()
        sched.step()
        vl = run_val()
        print(f"[recpol] ep {ep:3d} | train {tl/max(len(dl),1):.4f} | val(w-L1,normal) {vl:.4f} | {time.time()-t0:.0f}s", flush=True)
        ck = {"model": model.state_dict(), "val": vl,
              "meta": {"latent_dim": tr.Z[0].shape[1], "state_dim": len(cols), "hidden": args.hidden,
                       "depth": args.depth, "use_domain": use_domain, "state_columns": list(cols),
                       "frame_stride": stride, "d_max": args.d_max, "state_mean": sm, "state_std": ss,
                       "wm_checkpoint": args.checkpoint, "recovery": True,
                       "p_aug": args.p_aug, "alpha": args.alpha, "grid_w": args.grid_w}}
        torch.save(ck, out_dir / "last.pt")
        if vl < best - 1e-4:
            best, since = vl, 0
            torch.save(ck, out_dir / "best.pt")
        else:
            since += 1
            if since >= args.patience:
                print(f"[recpol] early-stop (best {best:.4f})", flush=True)
                break
    print(f"[recpol] DONE best val(w-L1,normal) {best:.4f} -> {out_dir}/best.pt "
          f"(baseline policy_prior_cd4 = 0.0699; want ~comparable)")


if __name__ == "__main__":
    main()
