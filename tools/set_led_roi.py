"""
Vẽ bbox chứa LED (cho latency tracker) — chạy MỘT LẦN, vẽ lại khi gắn lại LED.

Luồng:
  • Bật LED (UDP 0x01) để thấy chấm sáng.
  • Cửa sổ LIVE: chĩa/căn camera đến khi thấy LED, nhấn SPACE để chốt khung.
  • Kéo chuột khoanh ô quanh chấm LED → ENTER.
  • Lưu {x,y,w,h} vào data/led_roi.json (recorder + tracker tự đọc).

Chạy:  python tools/set_led_roi.py
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import json
import time
import socket
import threading
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT     = Path(__file__).resolve().parent.parent
SDP_PATH = str(Path.home() / "runcam.sdp")
OUT_FILE = ROOT / "data" / "led_roi.json"

W, H    = 640, 360                 # khớp capture.py
ESP32   = ("192.168.1.23", 4210)
LED_ON  = b"\x01"
LED_OFF = b"\x00"


class LatestFrame:
    """Đọc ffmpeg liên tục, luôn giữ frame mới nhất."""
    def __init__(self):
        self._proc = subprocess.Popen([
            "ffmpeg", "-protocol_whitelist", "file,rtp,udp",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", SDP_PATH, "-vf", f"scale={W}:{H}",
            "-pix_fmt", "bgr24", "-f", "rawvideo", "-",
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._n     = W * H * 3
        self._lock  = threading.Lock()
        self._frame = None
        self._stop  = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        out = self._proc.stdout
        while not self._stop.is_set():
            raw = out.read(self._n)
            if len(raw) < self._n:
                break
            f = np.frombuffer(raw, np.uint8).reshape((H, W, 3))
            with self._lock:
                self._frame = f

    def get(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def main():
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cam  = LatestFrame()

    print("Đang chờ stream camera...", flush=True)
    t0 = time.time()
    while cam.get() is None and time.time() - t0 < 5.0:
        time.sleep(0.05)
    if cam.get() is None:
        print("✗ Không có frame — stream chạy chưa? (bash scripts/wfb_up.sh)")
        cam.stop(); return

    # 1) Ngắm LIVE (LED bật) --------------------------------------------
    sock.sendto(LED_ON, ESP32)
    print("→ Căn camera đến khi thấy chấm LED. SPACE = chốt, q = thoát.")
    win = "Set LED ROI  (SPACE=chot  q=thoat)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    snap = None
    while True:
        f = cam.get()
        if f is not None:
            snap = f
            disp = f.copy()
            cv2.putText(disp, "Cham LED sang? SPACE=chot, q=thoat",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(win, disp)
        k = cv2.waitKey(30) & 0xFF
        if k == ord(" ") and snap is not None:
            break
        if k in (ord("q"), 27):
            cv2.destroyAllWindows(); sock.sendto(LED_OFF, ESP32); cam.stop()
            print("✗ Thoát."); return
    cv2.destroyAllWindows()

    # 2) Khoanh bbox quanh LED ------------------------------------------
    print("→ Kéo chuột khoanh ô quanh chấm LED (chừa rộng chút), rồi ENTER.")
    x, y, w, h = cv2.selectROI("Khoanh LED (ENTER de xac nhan)", snap, False, False)
    cv2.destroyAllWindows()
    sock.sendto(LED_OFF, ESP32)
    if w == 0 or h == 0:
        print("✗ Chưa khoanh — thoát."); cam.stop(); return

    roi = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    OUT_FILE.write_text(json.dumps(roi, indent=2))
    print(f"✓ Đã lưu bbox {roi} → {OUT_FILE}")

    # 3) Xem trước frame ĐÃ MASK ----------------------------------------
    f = cam.get()
    if f is not None:
        f[y:y+h, x:x+w] = 0
        cv2.rectangle(f, (x, y), (x+w, y+h), (0, 0, 255), 1)
        cv2.putText(f, "Frame sau khi mask (vung den = LED). Phim bat ky de thoat.",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.imshow("Preview masked", f)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    cam.stop()


if __name__ == "__main__":
    main()
