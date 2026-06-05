#!/usr/bin/env python3
"""Ghép frames/*.jpg của 1 session thành MP4 có overlay steer/throttle/mode/δ_cam — để inspect data.

Dùng:
  python tools/make_video.py data/raw/session_XXXX             # -> data/videos/session_XXXX.mp4
  python tools/make_video.py data/raw/session_XXXX out.mp4
  python tools/make_video.py --all                             # mọi session trong data/raw
"""
import csv
import glob
import os
import sys

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUTDIR = os.path.join(ROOT, "data", "videos")
FPS = 8.0  # frame rate thực tế ~8Hz


def load_actions(d):
    rows = {}
    p = os.path.join(d, "actions.csv")
    if not os.path.exists(p):
        return rows
    with open(p) as f:
        for row in csv.DictReader(f):
            try:
                rows[int(row["frame_idx"])] = row
            except (KeyError, ValueError):
                continue
    return rows


def _bar_h(img, cx, y, half, val, color):
    """Thanh ngang gốc giữa (steering)."""
    cv2.rectangle(img, (int(cx - half), y - 6), (int(cx + half), y + 6), (40, 40, 40), -1)
    sx = int(cx + val * half)
    x0, x1 = sorted((int(cx), sx))
    cv2.rectangle(img, (x0, y - 6), (x1, y + 6), color, -1)
    cv2.line(img, (int(cx), y - 10), (int(cx), y + 10), (255, 255, 255), 1)


def make(d, out=None):
    d = d.rstrip("/")
    frames = sorted(glob.glob(os.path.join(d, "frames", "*.jpg")))
    if not frames:
        print(f"  (bỏ qua, không có frame) {d}")
        return
    acts = load_actions(d)
    h, w = cv2.imread(frames[0]).shape[:2]
    if out is None:
        os.makedirs(OUTDIR, exist_ok=True)
        out = os.path.join(OUTDIR, os.path.basename(d) + ".mp4")
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    t0 = None
    for i, fp in enumerate(frames, 1):
        img = cv2.imread(fp)
        if img is None:
            continue
        row = acts.get(i, {})
        st = float(row.get("steering", 0) or 0)
        th = float(row.get("throttle", 0) or 0)
        md = row.get("mode", "?")
        dc = row.get("dcam_ms", "")
        t = row.get("t_ms")
        if t and t0 is None:
            try:
                t0 = int(t)
            except ValueError:
                t0 = None
        tt = (int(t) - t0) / 1000.0 if (t and t0 is not None) else 0.0
        txt = f"{i}/{len(frames)} t+{tt:5.2f}s mode={md} steer{st:+.3f} ga{th:+.3f}"
        if dc != "":
            try:
                txt += f" d{float(dc):.0f}ms"
            except ValueError:
                pass
        cv2.rectangle(img, (0, 0), (w, 20), (0, 0, 0), -1)
        cv2.putText(img, txt, (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
        # steering bar (đáy) + throttle bar (phải, ×3 cho dễ thấy vì ga nhỏ)
        _bar_h(img, w / 2, h - 14, w * 0.38, max(-1.0, min(1.0, st)), (0, 200, 255))
        tv = max(-1.0, min(1.0, th * 3))
        tx, cyt, vh = w - 14, h // 2, int(h * 0.3)
        cv2.rectangle(img, (tx - 6, cyt - vh), (tx + 6, cyt + vh), (40, 40, 40), -1)
        ty = int(cyt - tv * vh)
        y0, y1 = sorted((cyt, ty))
        cv2.rectangle(img, (tx - 6, y0), (tx + 6, y1), (100, 200, 80) if tv >= 0 else (60, 60, 230), -1)
        cv2.line(img, (tx - 10, cyt), (tx + 10, cyt), (255, 255, 255), 1)
        vw.write(img)
    vw.release()
    print(f"  -> {out}  ({len(frames)} frame)")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--all":
        for d in sorted(glob.glob(os.path.join(RAW, "session_*"))):
            print(os.path.basename(d))
            make(d)
    else:
        make(args[0], args[1] if len(args) > 1 else None)


if __name__ == "__main__":
    main()
