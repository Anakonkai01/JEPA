#!/usr/bin/env python3
"""Render an OPEN-LOOP steering demo MP4 (for slides) from data/demo/<session>/demo.json.

Left = camera frame; right panel = GOAL thumbnail + energy landscape E(steer) + steer gauge
(model vs human) + HUD. H.264 via ffmpeg pipe (plays in PowerPoint/Keynote). NO GPU needed.
Output: data/demo/<session>/<session>.mp4 (data/ is gitignored). Text is ASCII (cv2 font has
no Vietnamese diacritics) — the web UI (demo.html) keeps full Vietnamese.

    PYTHONPATH=src python scripts/demo_export_mp4.py session_20260608_173932 [--fps 10] [--stride 1]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW_DIRS = [ROOT / "data" / "raw_towerpro", ROOT / "data" / "raw_kds", ROOT / "data" / "raw_mixed"]
DEMO_DIR = ROOT / "data" / "demo"
FONT = cv2.FONT_HERSHEY_SIMPLEX
# BGR
GREEN = (80, 185, 63); ORANGE = (62, 131, 240); BLUE = (255, 166, 88)
DIM = (150, 148, 139); WHITE = (235, 232, 220); BG = (13, 11, 9); BANNER = (139, 217, 245)


def _raw_dir(s):
    for d in RAW_DIRS:
        if (d / s / "frames").is_dir():
            return d / s
    return None


def _txt(img, s, org, scale=0.5, col=WHITE, th=1):
    cv2.putText(img, s, org, FONT, scale, col, th, cv2.LINE_AA)


def _draw_landscape(img, x0, y0, w, h, grid, E, human_steer):
    emin, emax = min(E), max(E)
    X = lambda s: int(x0 + (s + 1) / 2 * w)
    Y = lambda e: int(y0 + h - (e - emin) / (emax - emin + 1e-9) * h)   # low E -> bottom
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (30, 24, 16), -1)
    cv2.line(img, (X(0), y0), (X(0), y0 + h), (66, 60, 52), 1)                  # center
    hx = X(human_steer)
    cv2.line(img, (hx, y0), (hx, y0 + h), ORANGE, 2)                            # human steer
    pts = np.array([[X(grid[i]), Y(E[i])] for i in range(len(grid))], np.int32)
    cv2.polylines(img, [pts], False, BLUE, 2, cv2.LINE_AA)                      # E(steer)
    k = int(np.argmin(E))
    cv2.circle(img, (X(grid[k]), Y(E[k])), 6, GREEN, -1)                        # model argmin
    cv2.circle(img, (X(grid[k]), Y(E[k])), 6, (13, 17, 13), 2)
    _txt(img, "<TRAI", (x0 + 4, y0 + h - 5), 0.4, DIM)
    _txt(img, "PHAI>", (x0 + w - 42, y0 + h - 5), 0.4, DIM)
    _txt(img, "ENERGY E(steer) - day . = model chon, vach = nguoi lai", (x0, y0 - 6), 0.42, DIM)


def _bar(img, cx, y, s, col, w):
    x = int(cx + s * w)
    cv2.rectangle(img, (min(cx, x), y), (max(cx, x), y + 10), col, -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--stride", type=int, default=1, help="lấy mỗi N frame (rút gọn video)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    demo = json.loads((DEMO_DIR / args.session / "demo.json").read_text())
    rd = _raw_dir(args.session)
    if rd is None:
        raise SystemExit(f"no raw frames for {args.session}")
    frames = demo["frames"][:: args.stride]
    grid, su = demo["grid"], demo["summary"]

    f0 = cv2.imread(str(rd / "frames" / f"{frames[0]['cur_frame']:06d}.jpg"))
    FH = 460
    sc = FH / f0.shape[0]
    FW = int(f0.shape[1] * sc) // 2 * 2
    PX = FW + 12
    PW = 560
    W = (FW + 12 + PW) // 2 * 2
    H = FH // 2 * 2

    out = Path(args.out) if args.out else DEMO_DIR / args.session / f"{args.session}.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(args.fps), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "20", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    gh = 150
    for n, fr in enumerate(frames):
        cam = cv2.imread(str(rd / "frames" / f"{fr['cur_frame']:06d}.jpg"))
        canvas = np.full((H, W, 3), BG, np.uint8)
        if cam is not None:
            canvas[:, :FW] = cv2.resize(cam, (FW, FH))
        # OPEN-LOOP banner over the cam
        cv2.rectangle(canvas, (0, 0), (FW, 22), (0, 0, 0), -1)
        _txt(canvas, "OPEN-LOOP: model DE XUAT lai, video chay theo NGUOI lai (khong phai xe tu chay)",
             (6, 15), 0.4, BANNER)
        # goal thumbnail
        goal = cv2.imread(str(rd / "frames" / f"{fr['goal_frame']:06d}.jpg"))
        _txt(canvas, "GOAL ~%.1fs truoc (model nham toi)" % demo["goal_lead_s"], (PX, 18), 0.42, DIM)
        if goal is not None:
            gw = min(int(goal.shape[1] * gh / goal.shape[0]), PW)
            canvas[26:26 + gh, PX:PX + gw] = cv2.resize(goal, (gw, gh))
        # landscape
        _draw_landscape(canvas, PX, 210, PW - 12, 150, grid, fr["E"], fr["human_steer"])
        # steer gauge (model green / human orange)
        gy = 392
        cx = PX + (PW - 12) // 2
        cv2.line(canvas, (PX, gy + 5), (PX + PW - 12, gy + 5), (66, 60, 52), 1)
        _bar(canvas, cx, gy - 12, fr["human_steer"], ORANGE, (PW - 12) / 2 - 4)
        _bar(canvas, cx, gy + 6, fr["model_steer"], GREEN, (PW - 12) / 2 - 4)
        # HUD numbers
        _txt(canvas, "MODEL %+.2f" % fr["model_steer"], (PX, gy + 44), 0.62, GREEN, 2)
        _txt(canvas, "NGUOI %+.2f" % fr["human_steer"], (PX + 175, gy + 44), 0.62, ORANGE, 2)
        _txt(canvas, "contrast %.2f" % fr["contrast"], (PX + 355, gy + 44), 0.55, WHITE, 1)
        if fr["is_turn"]:
            ok = fr["sign_ok"]
            _txt(canvas, "QUEO - %s" % ("dung chieu" if ok else "SAI chieu"),
                 (PX, gy + 70), 0.5, GREEN if ok else (60, 60, 240), 1)
        else:
            _txt(canvas, "di thang", (PX, gy + 70), 0.5, DIM, 1)
        # session headline (held-out)
        _txt(canvas, "VAL held-out: sign-turn %.0f%%  |dsteer|med %.3f  contrast med %.2f  (n=%d)"
             % (su["sign_acc_turn"] * 100, su["median_abs_dsteer"], su["median_contrast"], su["n"]),
             (PX, H - 12), 0.42, DIM)
        _txt(canvas, "frame %d/%d  #%d" % (n + 1, len(frames), fr["cur_frame"]),
             (8, H - 10), 0.42, DIM)
        ff.stdin.write(canvas.tobytes())

    ff.stdin.close()
    ff.wait()
    print(f"[mp4] {args.session} -> {out}  ({len(frames)} frame @ {args.fps}fps, {W}x{H})")


if __name__ == "__main__":
    main()
