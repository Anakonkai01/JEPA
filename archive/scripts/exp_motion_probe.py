#!/usr/bin/env python3
"""Stage-0 experiment for direction C: IS SPEED ENCODED IN A CLIP LATENT?

Honest minimal test (no world-model / CEM needed). For a set of sessions we build
two representations of each center frame and probe how well each predicts the car's
actual GPS speed (and throttle):

  * single-frame latent  = mean-pooled V-JEPA T=1 token  (reuse cached latents_towerpro)
  * clip latent          = mean-pooled V-JEPA token of a T-frame clip ending at the
                           center frame, stride `s`  (motion enters via the tubelet conv)

If the clip latent predicts speed MUCH better than the single frame, motion/velocity
IS captured -> direction C (patch-token + clip) is worth building. If not, we learned
it cheaply. Probe = ridge regression; train/test split BY SESSION (no frame leakage).

    PYTHONPATH=src python scripts/exp_motion_probe.py --clip-T 4 --clip-stride 2
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_targets(session_dir: Path):
    """frame_idx -> (t_scene_ms, throttle, steering); plus gps interp of speed."""
    acts = read_csv(session_dir / "actions_synced.csv")
    fi = np.array([int(r["frame_idx"]) for r in acts])
    t = np.array([float(r["t_scene_ms"]) for r in acts])
    thr = np.array([float(r["throttle"]) for r in acts])
    gps = read_csv(session_dir / "gps.csv")
    gt = np.array([float(r["t_ms"]) for r in gps])
    gs = np.array([float(r["speed"]) for r in gps])
    order = np.argsort(gt)
    speed = np.interp(t, gt[order], gs[order])           # gps speed at each frame's scene time
    return fi, t, thr, speed


@torch.no_grad()
def encode_clips(enc, session_dir: Path, center_fidx, clip_T, stride, device,
                 image_size=384, batch=16):
    """Return (M,1024) mean-pooled clip latents for the centers we can build a full clip for,
    plus a boolean mask over center_fidx of which were buildable."""
    framedir = session_dir / "frames"

    def load(fi):
        p = framedir / f"{fi:06d}.jpg"
        img = Image.open(p).convert("RGB").resize((image_size, image_size), Image.BILINEAR)
        x = torch.from_numpy(np.asarray(img, np.float32)).permute(2, 0, 1) / 255.0
        return (x - IMAGENET_MEAN) / IMAGENET_STD

    lats, mask, buf = [], [], []
    for fi in center_fidx:
        idxs = [fi - k * stride for k in range(clip_T - 1, -1, -1)]   # oldest..center
        if idxs[0] < 1 or not all((framedir / f"{j:06d}.jpg").exists() for j in idxs):
            mask.append(False); continue
        mask.append(True)
        clip = torch.stack([load(j) for j in idxs], dim=1)            # (3,T,H,W)
        buf.append(clip)
        if len(buf) == batch:
            lats.append(_enc(enc, buf, device)); buf = []
    if buf:
        lats.append(_enc(enc, buf, device))
    out = torch.cat(lats) if lats else torch.empty(0, 1024)
    return out.numpy(), np.array(mask)


def _enc(enc, buf, device):
    x = torch.stack(buf).to(device)                                   # (B,3,T,H,W)
    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
        tok = enc(x)                                                  # (B, N, 1024)
    return tok.float().mean(1).cpu()                                  # (B,1024)


def ridge_probe(Xtr, ytr, Xte, yte, alpha=10.0):
    """Standardize X, ridge-fit, return (R2, MAE) on test."""
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    Xtr = (Xtr - mu) / sd; Xte = (Xte - mu) / sd
    ym = ytr.mean()
    A = Xtr.T @ Xtr + alpha * np.eye(Xtr.shape[1])
    w = np.linalg.solve(A, Xtr.T @ (ytr - ym))
    pred = Xte @ w + ym
    ss_res = ((yte - pred) ** 2).sum()
    ss_tot = ((yte - yte.mean()) ** 2).sum() + 1e-9
    return 1 - ss_res / ss_tot, np.abs(yte - pred).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latents-dir", default="data/latents_towerpro")
    ap.add_argument("--raw-dir", default="data/raw_towerpro")
    ap.add_argument("--sessions", nargs="*", default=None, help="default: 06-08 sessions w/ gps")
    ap.add_argument("--clip-T", type=int, default=4)
    ap.add_argument("--clip-stride", type=int, default=2)
    ap.add_argument("--n-test", type=int, default=3, help="held-out sessions")
    ap.add_argument("--image-size", type=int, default=384)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    raw = Path(args.raw_dir); latd = Path(args.latents_dir)
    if args.sessions:
        sess = args.sessions
    else:
        sess = sorted(p.name for p in raw.glob("session_20260608_*")
                      if (p / "gps.csv").exists() and (latd / f"{p.name}.pt").exists())
    print(f"[motion-probe] T={args.clip_T} stride={args.clip_stride} | {len(sess)} sessions | {device}")
    enc = load_encoder(device)

    rows = []  # (session, X_single, X_clip, speed, throttle)
    for s in sess:
        fi, t, thr, speed = load_targets(raw / s)
        cache = torch.load(latd / f"{s}.pt", map_location="cpu")
        cfi = cache["frame_idx"].numpy(); clat = cache["latents"].numpy()
        pos = {int(f): k for k, f in enumerate(cfi)}
        keep = np.array([f in pos for f in fi])
        fi, t, thr, speed = fi[keep], t[keep], thr[keep], speed[keep]
        Xs = clat[[pos[int(f)] for f in fi]]
        Xc, mask = encode_clips(enc, raw / s, fi, args.clip_T, args.clip_stride, device, args.image_size)
        Xs, speed_m, thr_m = Xs[mask], speed[mask], thr[mask]
        if len(Xc) == 0:
            print(f"  {s}: no clips"); continue
        rows.append((s, Xs, Xc, speed_m, thr_m))
        print(f"  {s}: {len(Xc)} clips | vmean {speed_m.mean():.2f}")

    te = set(r[0] for r in rows[-args.n_test:]); tr = [r for r in rows if r[0] not in te]
    teR = [r for r in rows if r[0] in te]
    def cat(rs, i): return np.concatenate([r[i] for r in rs])
    for tgt_i, tgt in [(3, "speed(m/s)"), (4, "throttle")]:
        ytr, yte = cat(tr, tgt_i), cat(teR, tgt_i)
        for name, xi in [("single-frame T=1", 1), (f"clip T={args.clip_T} s={args.clip_stride}", 2)]:
            r2, mae = ridge_probe(cat(tr, xi), ytr, cat(teR, xi), yte)
            print(f"  [{tgt:>11}] {name:<20} R2={r2:6.3f}  MAE={mae:.3f}")
    print(f"\n train {len(tr)} sess / test {len(teR)} sess. ĐỌC: clip R2(speed) >> single = motion ĐƯỢC mã hóa -> C đáng xây.")


if __name__ == "__main__":
    main()
