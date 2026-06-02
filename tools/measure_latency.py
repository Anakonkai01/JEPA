"""
Đo CAMERA_LATENCY (độ trễ glass→PC của đường camera) — chạy MỘT LẦN để calibrate.

Nguyên lý (phương pháp LED):
  PC gửi UDP bật LED onboard ESP32 + ghi t0
  → camera nhìn thấy LED sáng ở frame nào đó (t_frame)
  → latency = t_frame − t0
  Lặp N lần, lấy trung vị (median) cho ổn định.

Yêu cầu:
  • ESP32 đã flash firmware (hỗ trợ UDP 0x01=LED on, 0x00=LED off).
  • Stream camera đang chạy (bash scripts/wfb_up.sh).
  • CHĨA CAMERA VÀO LED onboard của ESP32, phòng hơi tối để LED nổi bật.

Kết quả ghi vào data/camera_latency.txt → recorder.py tự đọc.

Chạy:  conda activate ai && python tools/measure_latency.py
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import time
import socket
import threading
import subprocess
import statistics
from pathlib import Path

import cv2
import numpy as np

ROOT     = Path(__file__).resolve().parent.parent
SDP_PATH = str(Path.home() / "runcam.sdp")
OUT_FILE = ROOT / "data" / "camera_latency.txt"

W, H        = 640, 360
ESP32       = ("192.168.1.23", 4210)
N_TRIALS    = 15
LED_ON      = b"\x01"
LED_OFF     = b"\x00"


# ── ffmpeg reader thread: luôn giữ frame MỚI NHẤT + thời điểm đọc ──────
class LatestFrame:
    def __init__(self):
        self._proc = subprocess.Popen([
            "ffmpeg", "-protocol_whitelist", "file,rtp,udp",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", SDP_PATH,
            "-vf", f"scale={W}:{H}",
            "-pix_fmt", "bgr24", "-f", "rawvideo", "-",
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._nbytes = W * H * 3
        self._lock   = threading.Lock()
        self._frame  = None
        self._t      = 0.0
        self._stop   = threading.Event()
        self._th     = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    def _run(self):
        out = self._proc.stdout
        while not self._stop.is_set():
            raw = out.read(self._nbytes)
            if len(raw) < self._nbytes:
                break
            f = np.frombuffer(raw, np.uint8).reshape((H, W, 3))
            with self._lock:
                self._frame = f
                self._t     = time.time()   # thời điểm frame ra khỏi ffmpeg

    def get(self):
        with self._lock:
            return (None, 0.0) if self._frame is None else (self._frame.copy(), self._t)

    def stop(self):
        self._stop.set()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def wait_frame(cam, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        f, t = cam.get()
        if f is not None:
            return f, t
        time.sleep(0.02)
    return None, 0.0


def main():
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cam  = LatestFrame()

    print("Đang chờ stream camera...", flush=True)
    frame, _ = wait_frame(cam)
    if frame is None:
        print("✗ Không có frame — stream camera chạy chưa? (bash scripts/wfb_up.sh)")
        cam.stop(); return

    # 1) Ngắm camera vào LED (LIVE) -------------------------------------
    sock.sendto(LED_ON, ESP32)   # bật LED để ngắm
    print("→ Chĩa camera vào LED đến khi thấy chấm sáng. SPACE = chốt khung, q = thoát.")
    aim_win = "Ngam camera vao LED  (SPACE=chot  q=thoat)"
    cv2.namedWindow(aim_win, cv2.WINDOW_NORMAL)
    snap = None
    while True:
        f, _ = cam.get()
        if f is not None:
            snap = f
            disp = f.copy()
            cv2.putText(disp, "Chia camera vao LED. SPACE=chot, q=thoat",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(aim_win, disp)
        k = cv2.waitKey(30) & 0xFF
        if k == ord(" ") and snap is not None:
            break
        if k in (ord("q"), 27):
            cv2.destroyAllWindows(); sock.sendto(LED_OFF, ESP32); cam.stop()
            print("✗ Thoát."); return
    cv2.destroyAllWindows()

    # 2) Khoanh ô quanh chấm LED trên frame vừa chốt --------------------
    print("→ Kéo chuột khoanh vùng quanh chấm LED, rồi ENTER/SPACE.")
    x, y, w, h = cv2.selectROI("Chon vung LED (ENTER de xac nhan)", snap, False, False)
    cv2.destroyAllWindows()
    sock.sendto(LED_OFF, ESP32)
    if w == 0 or h == 0:
        print("✗ Chưa chọn vùng — thoát.")
        cam.stop(); return

    # Đo theo ĐIỂM SÁNG NHẤT trong ô (blur nhẹ chống nhiễu 1 pixel) —
    # bắt được chấm LED nhỏ kể cả khi nền tối, không bị "pha loãng" như mean.
    def roi_spot(f):
        g = cv2.cvtColor(f[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        return float(g.max())

    # 3) Auto-calibrate ngưỡng sáng -------------------------------------
    sock.sendto(LED_OFF, ESP32); time.sleep(0.5)
    f_off, _ = wait_frame(cam); base = roi_spot(f_off)
    sock.sendto(LED_ON, ESP32); time.sleep(0.5)
    f_on, _ = wait_frame(cam);  lit = roi_spot(f_on)
    sock.sendto(LED_OFF, ESP32); time.sleep(0.5)
    print(f"   ROI điểm sáng nhất: tắt={base:.0f}  bật={lit:.0f}  (chênh {lit-base:.0f})")
    if lit - base < 15:
        print("⚠ Chênh lệch quá nhỏ — khoanh ROI sát chấm LED hơn / đưa LED vào khung rõ hơn.")
        cam.stop(); return
    thr = (base + lit) / 2.0

    # 4) Đo N lần (có cửa sổ xem trực tiếp) ------------------------------
    win = "Measure latency — LED nhay (q=thoat)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    aborted = False

    def preview(f, spot, state, idx):
        disp = f.copy()
        cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(disp, f"trial {idx}/{N_TRIALS}  spot:{spot:.0f}  thr:{thr:.0f}  LED:{state}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow(win, disp)
        return (cv2.waitKey(1) & 0xFF) == ord("q")

    latencies = []
    for i in range(N_TRIALS):
        sock.sendto(LED_OFF, ESP32)
        t_off = time.time()
        while time.time() - t_off < 0.4:      # chờ LED tắt hẳn + frame ổn định
            f, _ = cam.get()
            if f is not None and preview(f, roi_spot(f), "OFF", i + 1):
                aborted = True; break
        if aborted:
            break

        t0 = time.time()
        sock.sendto(LED_ON, ESP32)
        hit = None
        while time.time() - t0 < 1.0:         # timeout 1s/lần
            f, t = cam.get()
            if f is not None:
                spot = roi_spot(f)
                if preview(f, spot, "ON", i + 1):
                    aborted = True; break
                if t > t0 and spot > thr:
                    hit = t - t0
                    break
            else:
                time.sleep(0.001)
        if aborted:
            break

        if hit is not None:
            latencies.append(hit)
            print(f"   [{i+1:2d}/{N_TRIALS}] {hit*1000:6.1f} ms")
        else:
            print(f"   [{i+1:2d}/{N_TRIALS}] (không phát hiện — bỏ qua)")

    sock.sendto(LED_OFF, ESP32)
    cam.stop()
    cv2.destroyAllWindows()
    if aborted:
        print("✗ Đã hủy.")
        return

    # 4) Kết quả ---------------------------------------------------------
    if len(latencies) < 3:
        print("✗ Quá ít mẫu hợp lệ — kiểm tra LED có trong khung hình + ESP32 nhận UDP.")
        return
    med = statistics.median(latencies)
    print("\n────────── KẾT QUẢ ──────────")
    print(f"  mẫu hợp lệ : {len(latencies)}/{N_TRIALS}")
    print(f"  median     : {med*1000:.1f} ms")
    print(f"  mean ± std : {statistics.mean(latencies)*1000:.1f} ± "
          f"{statistics.pstdev(latencies)*1000:.1f} ms")
    print(f"  min / max  : {min(latencies)*1000:.1f} / {max(latencies)*1000:.1f} ms")
    OUT_FILE.write_text(f"{med:.4f}\n")
    print(f"\n✓ Đã ghi {med:.4f}s vào {OUT_FILE} — recorder.py sẽ tự đọc.")


if __name__ == "__main__":
    main()
