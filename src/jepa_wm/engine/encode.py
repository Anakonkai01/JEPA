"""Offline encoding: frames -> frozen V-JEPA 2.1 latents (cached once).

V-JEPA 2.1 ViT-L is loaded via torch.hub (the 2.1 checkpoints are NOT on
HuggingFace — that's 2.0). The hub entry returns (encoder, predictor); we use
the encoder in single-frame mode:

    frame (B,3,1,384,384) -> encoder -> (B, 576, 1024) spatial tokens -> mean-pool -> (B, 1024)

Per session we write ``data/latents/<session>.pt = {"latents": (N,1024),
"frame_idx": (N,)}`` aligned 1:1 with ``actions_synced.csv`` rows, consumed by
LatentTransitionDataset. ⚠️ The encoder is frozen — never backprop through it.
See docs/PLAN.md "Key optimization".
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

HUB_REPO = "facebookresearch/vjepa2"
HUB_ENTRY = "vjepa2_1_vit_large_384"
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


def load_encoder(device="cuda"):
    enc, _ = torch.hub.load(HUB_REPO, HUB_ENTRY, trust_repo=True)
    enc.eval().to(device)
    for p in enc.parameters():
        p.requires_grad_(False)
    return enc


class _FrameSet(Dataset):
    def __init__(self, session_dir: Path, image_size=384):
        self.dir = session_dir
        self.size = image_size
        self.fidx = []
        with open(session_dir / "actions_synced.csv") as f:
            for row in csv.DictReader(f):
                self.fidx.append(int(row["frame_idx"]))

    def __len__(self):
        return len(self.fidx)

    def __getitem__(self, i):
        fi = self.fidx[i]
        p = self.dir / "frames" / f"{fi:06d}.jpg"
        img = Image.open(p).convert("RGB").resize((self.size, self.size), Image.BILINEAR)
        x = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
        return (x - IMAGENET_MEAN) / IMAGENET_STD, fi


@torch.no_grad()
def encode_session(enc, session_dir: Path, out_path: Path, device="cuda",
                   image_size=384, batch_size=32, num_workers=8):
    ds = _FrameSet(session_dir, image_size)
    if len(ds) == 0:
        return 0
    dl = DataLoader(ds, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)
    lats, fidx = [], []
    for x, fi in dl:
        x = x.to(device, non_blocking=True).unsqueeze(2)        # (B,3,1,384,384)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
            tok = enc(x)                                        # (B, 576, 1024)
        lats.append(tok.float().mean(1).cpu())                 # (B, 1024)
        fidx.extend(fi.tolist())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"latents": torch.cat(lats), "frame_idx": torch.tensor(fidx)}, out_path)
    return len(ds)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--out-dir", default="data/latents")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--image-size", type=int, default=384)
    ap.add_argument("--num-workers", type=int, default=8)
    ap.add_argument("--sessions", nargs="*", default=None, help="subset (default: all synced)")
    args = ap.parse_args(argv)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    raw, out = Path(args.raw_dir), Path(args.out_dir)
    sessions = args.sessions or sorted(
        p.name for p in raw.glob("session_*") if (p / "actions_synced.csv").exists())
    print(f"[encode] V-JEPA 2.1 ViT-L | {len(sessions)} sessions -> {out}")
    enc = load_encoder(device)
    total = 0
    import time
    for i, s in enumerate(sessions):
        op = out / f"{s}.pt"
        if op.exists():
            print(f"  [{i+1}/{len(sessions)}] {s} skip (exists)")
            continue
        t0 = time.time()
        n = encode_session(enc, raw / s, op, device, args.image_size, args.batch_size, args.num_workers)
        total += n
        print(f"  [{i+1}/{len(sessions)}] {s}: {n} frames in {time.time()-t0:.0f}s", flush=True)
    print(f"[encode] done: {total} frames -> {out}")


if __name__ == "__main__":
    main()
