#!/usr/bin/env python3
"""Measure whether the FROZEN V-JEPA 2.1 single-frame latent carries SPEED.

Reproducible test for the report's "encoder is velocity-blind" claim. For every frame we
mean-pool the per-frame patch map (576x1024 -> 1024) and try to predict GPS speed (m/s)
from it with ridge regression. Fit on TRAIN sessions, report R^2 on held-out VAL frames
(the honest number: positive R^2 => latent encodes speed; <=0 => it does not).

    PYTHONPATH=src python scripts/measure_speed_r2.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import torch

from jepa_wm.data.dataset import frozen_split
from jepa_wm.data.state import load_state

CK = "checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt"


def gather(sessions, roots):
    X, y = [], []
    for s in sessions:
        root = next((r for r in roots if s in r["_sessions"]), None)
        if root is None:
            continue
        lat = np.load(Path(root["patch_dir"]) / f"{s}.npy", mmap_mode="r")  # (T,576,1024)
        try:
            st, _ = load_state(Path(root["raw_dir"]) / s, columns=("speed",))
        except Exception:
            continue
        T = min(len(lat), len(st))
        if T < 5:
            continue
        pooled = np.asarray(lat[:T], dtype=np.float32).mean(axis=1)  # (T,1024)
        X.append(pooled)
        y.append(st[:T, 0].astype(np.float32))
    return np.concatenate(X), np.concatenate(y)


def ridge_fit(Xtr, ytr, lam):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    Xz = (Xtr - mu) / sd
    d = Xz.shape[1]
    A = Xz.T @ Xz + lam * np.eye(d, dtype=np.float32)
    w = np.linalg.solve(A, Xz.T @ (ytr - ytr.mean()))
    b = ytr.mean()
    return w, b, mu, sd


def r2(y, yhat):
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return 1.0 - ss_res / (ss_tot + 1e-12)


def main():
    ck = torch.load(CK, map_location="cpu", weights_only=False)
    roots = ck["cfg"]["data"]["roots"]
    for r in roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    sessions = sorted(s for r in roots for s in r["_sessions"])
    sp = Path(CK).parent / "split.json"
    tr, va, _ = frozen_split(sp, sessions, val_frac=ck["cfg"]["data"].get("val_frac", 0.2),
                             seed=ck["cfg"].get("seed", 0), save=False)
    # subsample sessions: a ridge R^2 needs far fewer than all 167 train sessions, and
    # this keeps disk I/O light (avoids starving a concurrent job).
    tr = tr[::4][:40]            # ~40 train sessions
    va = va[:20]                 # 20 held-out val sessions
    print(f"train sessions {len(tr)} (subsampled) | val sessions {len(va)} (subsampled)")
    Xtr, ytr = gather(tr, roots)
    Xva, yva = gather(va, roots)
    print(f"train frames {len(ytr):,} | val frames {len(yva):,}")
    print(f"speed: train mean {ytr.mean():.3f} std {ytr.std():.3f} | val mean {yva.mean():.3f} std {yva.std():.3f} m/s")

    best = None
    for lam in [1.0, 10.0, 100.0, 1000.0, 10000.0]:
        w, b, mu, sd = ridge_fit(Xtr, ytr, lam)
        yhat_tr = ((Xtr - mu) / sd) @ w + b
        yhat_va = ((Xva - mu) / sd) @ w + b
        rtr, rva = r2(ytr, yhat_tr), r2(yva, yhat_va)
        print(f"  ridge lam={lam:>8.0f}  R2 train={rtr:+.3f}  R2 VAL(held-out)={rva:+.3f}")
        if best is None or rva > best[1]:
            best = (lam, rva, rtr)
    print(f"\n==> BEST held-out R2(speed) = {best[1]:+.3f}  (lam={best[0]:.0f}, train R2={best[2]:+.3f})")
    print("    R2<=0  => pooled single-frame V-JEPA latent does NOT linearly encode speed.")
    Path("data/demo/speed_r2.json").write_text(json.dumps(
        {"best_val_r2": float(best[1]), "lam": float(best[0]), "train_r2": float(best[2]),
         "n_train_frames": int(len(ytr)), "n_val_frames": int(len(yva)),
         "speed_std_mps": float(yva.std())}))


if __name__ == "__main__":
    main()
