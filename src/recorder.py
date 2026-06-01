"""
Data collection — lái xe bằng WASD, lưu frame + action.

Điều khiển (pynput — key-up thật, không cần timeout):
  W          giữ → tiến   | buông → dừng
  S          giữ → lùi    | buông → dừng  (ESC cần Mode 3 hoặc double-tap)
  A          giữ → lái trái  | buông → thẳng
  D          giữ → lái phải  | buông → thẳng
  Space      dừng ngay (override tất cả)
  R          bắt đầu / kết thúc ghi session
  ESC        thoát

Dữ liệu lưu tại:
  data/raw/session_YYYYMMDD_HHMMSS/
    frames/  000001.jpg  000002.jpg  ...
    actions.csv   (frame_idx, timestamp, steering, throttle)
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import csv
import sys
import time
import threading
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from pynput import keyboard as kb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from capture    import FrameCapture
from controller import ESPController

# ── Cấu hình ──────────────────────────────────────────────────
DATA_DIR     = ROOT / "data" / "raw"
JPEG_QUALITY = 90
SEND_HZ      = 10
SAVE_HZ      = 10

THROTTLE     = 0.09       # ~1571µs — tiến chậm vừa phải
STEER_AMOUNT = 0.75

# ── Keyboard state (pynput thread → main thread) ───────────────
_keys  : set[str] = set()
_klock = threading.Lock()
_quit  = threading.Event()
_rec   = threading.Event()   # edge: nhấn R 1 lần

def _press(key):
    if key == kb.Key.esc:
        _quit.set()
        return
    if key == kb.Key.space:
        with _klock: _keys.add(' ')
        return
    try:
        c = key.char.lower()
        with _klock: _keys.add(c)
        if c == 'r':
            _rec.set()
    except AttributeError:
        pass

def _release(key):
    if key == kb.Key.space:
        with _klock: _keys.discard(' ')
        return
    try:
        with _klock: _keys.discard(key.char.lower())
    except AttributeError:
        pass

# ── Session management ─────────────────────────────────────────
recording   = False
session_dir : Path | None = None
csv_file    = None
csv_writer  = None
frame_count = 0


def start_session():
    global recording, session_dir, csv_file, csv_writer, frame_count
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = DATA_DIR / f"session_{ts}"
    (session_dir / "frames").mkdir(parents=True, exist_ok=True)
    csv_file   = open(session_dir / "actions.csv", "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["frame_idx", "timestamp", "steering", "throttle"])
    frame_count = 0
    recording   = True
    print(f"[REC] ● Bắt đầu → {session_dir}", flush=True)


def stop_session():
    global recording, csv_file, csv_writer
    recording = False
    if csv_file:
        csv_file.close()
        csv_file   = None
        csv_writer = None
    print(f"[REC] ○ Kết thúc — {frame_count} frames → {session_dir}", flush=True)


def save_frame(frame: np.ndarray, steering: float, throttle: float):
    global frame_count
    if not recording or session_dir is None or csv_writer is None:
        return
    frame_count += 1
    cv2.imwrite(
        str(session_dir / "frames" / f"{frame_count:06d}.jpg"),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
    )
    csv_writer.writerow([frame_count, round(time.time(), 4),
                         round(steering, 4), round(throttle, 4)])


# ── Overlay HUD ───────────────────────────────────────────────
def draw_overlay(frame: np.ndarray, steering: float, throttle: float) -> np.ndarray:
    out  = frame.copy()
    h, w = out.shape[:2]
    col  = (0, 0, 255) if recording else (200, 200, 200)

    for i, txt in enumerate([
        f"{'● REC' if recording else '○ STANDBY'}  frame:{frame_count}",
        f"Steer : {steering:+.2f}",
        f"Throttle: {throttle:.2f}",
    ]):
        cv2.putText(out, txt, (12, 30 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)

    # Steering bar
    y  = h - 20
    x0, x1 = w // 4, 3 * w // 4
    mid = (x0 + x1) // 2
    pos = int(mid + steering * (x1 - mid))
    cv2.line(out,   (x0, y), (x1, y), (60, 60, 60), 3)
    cv2.line(out,   (mid, y - 6), (mid, y + 6), (120, 120, 120), 2)
    cv2.circle(out, (pos, y), 9, (0, 220, 0), -1)

    cv2.putText(out, "W=tien  S=lui  A/D=lai(giu)  Space=dung  R=rec  ESC=thoat",
                (12, h - 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)
    return out


# ── Main ───────────────────────────────────────────────────────
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cap  = FrameCapture()
    ctrl = ESPController()

    listener = kb.Listener(on_press=_press, on_release=_release)
    listener.start()

    cap.start()
    cv2.namedWindow("JEPA Recorder — WASD", cv2.WINDOW_NORMAL)
    print("Đang kết nối stream... (nhấn W/A/D để lái, R để ghi, ESC thoát)", flush=True)

    send_interval = 1.0 / SEND_HZ
    save_interval = 1.0 / SAVE_HZ
    last_send = last_save = 0.0

    steering = throttle = 0.0

    try:
        while not _quit.is_set():
            frame = cap.get_frame(timeout=0.05)
            now   = time.time()

            # ── Toggle recording (edge trigger) ───────────────────
            if _rec.is_set():
                _rec.clear()
                if not recording:
                    start_session()
                else:
                    stop_session()

            # ── Tính steering & throttle từ key state ─────────────
            with _klock:
                held = frozenset(_keys)

            if ' ' in held:                     # Space = dừng khẩn cấp
                throttle = 0.0
                steering = 0.0
            else:
                if 'w' in held:
                    throttle = THROTTLE         # tiến
                elif 's' in held:
                    throttle = -THROTTLE        # lùi (âm → controller gửi byte < 64)
                else:
                    throttle = 0.0
                if 'a' in held:
                    steering = -STEER_AMOUNT
                elif 'd' in held:
                    steering = STEER_AMOUNT
                else:
                    steering = 0.0

            # ── Gửi UDP @ SEND_HZ ─────────────────────────────────
            if now - last_send >= send_interval:
                ctrl.send(steering=steering, throttle=throttle)
                last_send = now

            # ── Lưu frame @ SAVE_HZ ───────────────────────────────
            if frame is not None:
                if recording and now - last_save >= save_interval:
                    save_frame(frame, steering, throttle)
                    last_save = now
                cv2.imshow("JEPA Recorder — WASD",
                           draw_overlay(frame, steering, throttle))

            cv2.waitKey(1)   # pump OpenCV event queue

    except KeyboardInterrupt:
        pass
    finally:
        if recording:
            stop_session()
        ctrl.stop()
        ctrl.close()
        cap.stop()
        # stop listener từ thread riêng để tránh deadlock khi gọi từ main
        t = threading.Thread(target=listener.stop, daemon=True)
        t.start()
        t.join(timeout=1.0)
        cv2.destroyAllWindows()
        print("Done.", flush=True)


if __name__ == "__main__":
    main()
