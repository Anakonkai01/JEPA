#!/usr/bin/env python3
"""N5 — montage of representative onboard frames (what the frozen encoder sees).

Samples one mid-session frame from several sessions spread across time-of-day and both servo
domains, to show the visual variety (lighting, scene, shadows) the encoder must handle.

    python scripts/plot_frame_montage.py [--n 8]

Reads JPGs from data/raw_*/<session>/frames/ (gitignored data).
"""
import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt

OUT = Path("docs/report/figures/fig_frame_montage.png")
TS = re.compile(r"session_(\d{8})_(\d{6})")


def sessions():
    out = []
    for dom, root in [("KDS", "data/raw_kds"), ("TowerPro", "data/raw_towerpro")]:
        for s in sorted(Path(root).glob("session_*")):
            fr = s / "frames"
            if not fr.is_dir():
                continue
            jpgs = sorted(fr.glob("*.jpg"))
            if len(jpgs) < 20:
                continue
            m = TS.search(s.name)
            hhmm = f"{m.group(2)[:2]}:{m.group(2)[2:4]}" if m else "??:??"
            out.append(dict(name=s.name, dom=dom, hhmm=hhmm, jpgs=jpgs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    ss = sessions()
    if not ss:
        raise SystemExit("no sessions with frames found under data/raw_*/")
    # spread across time-of-day; keep both domains represented
    ss.sort(key=lambda d: d["hhmm"])
    n = min(args.n, len(ss))
    idx = [round(i * (len(ss) - 1) / (n - 1)) for i in range(n)] if n > 1 else [0]
    picks = [ss[i] for i in dict.fromkeys(idx)]

    cols = 4
    rows = (len(picks) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(13, 3.0 * rows))
    axes = axes.ravel()
    for ax in axes:
        ax.axis("off")
    for ax, s in zip(axes, picks):
        jp = s["jpgs"][len(s["jpgs"]) // 2]  # mid-session frame
        ax.imshow(mpimg.imread(jp))
        ax.set_title(f"{s['hhmm']}  ·  {s['dom']}", fontsize=10, fontweight="bold")
        ax.axis("off")
    fig.suptitle("What the frozen encoder sees — representative onboard frames across time of day & both servo domains",
                 fontsize=13, fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=130)
    print(f"wrote {OUT}  ({len(picks)} frames from {len(ss)} sessions)")


if __name__ == "__main__":
    main()
