"""
Data collection (FlySky i-BUS) — xe do FlySky lái, PC ghi THỤ ĐỘNG,
latency được đo REALTIME bằng LED gắn cố định trong khung hình.

Luồng:
  ESP32 (mode RECORD) gửi telemetry UDP @50Hz: action + esp_ms + seq + cờ rec (CH10)
  RunCam → WFB-NG → ffmpeg → (frame BGR, t_read)  (capture.py)
  recorder:
    • TelemetryReceiver: nhận telemetry → ring buffer ~1s, gửi heartbeat + lệnh LED
    • LatencyTracker: cứ ~2s nháy LED trong ROI cố định → đo trễ camera realtime
    • Mỗi frame: đo sáng ROI (cho tracker) → TÔ ĐEN ROI → lưu frame sạch
    • Ghép action tại (t_read − latency_hiện_tại); ghi actions.csv + latency.csv

Điều khiển ghi:  switch CH10 (>1500 = ghi) → tự start/stop session.
Thoát:           phím Q / ESC trên cửa sổ video.

Chuẩn bị 1 lần: python tools/set_led_roi.py  (vẽ bbox chứa LED → data/led_roi.json)
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import csv
import sys
import json
import time
import socket
import struct
import statistics
import threading
from collections import deque
from pathlib import Path
from datetime import datetime

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from capture import FrameCapture

# ── Cấu hình ──────────────────────────────────────────────────
DATA_DIR     = ROOT / "data" / "raw"
ROI_FILE     = ROOT / "data" / "led_roi.json"
LAT_FILE     = ROOT / "data" / "camera_latency.txt"
JPEG_QUALITY = 90
SAVE_HZ      = 10

ESP32_HOST   = "192.168.1.23"
ESP32_PORT   = 4210
HEARTBEAT_S  = 0.5

FLASH_PERIOD = 2.0           # tracker nháy LED mỗi 2s
LED_ON, LED_OFF = b"\x01", b"\x00"

# Telemetry struct (khớp firmware, little-endian, packed):
#   magic B|mode B|seq I|esp_ms I|steering f|throttle f|ch_steer H|ch_throt H|ch_record H|rec B
TELEM_FMT   = "<BBIIffHHHB"
TELEM_SIZE  = struct.calcsize(TELEM_FMT)   # 25
TELEM_MAGIC = 0xAC
MODE_NAME   = {0: "NEUTRAL", 1: "RECORD", 2: "AUTO"}


def load_fallback_latency(default=0.19):
    try:
        return float(LAT_FILE.read_text().strip())
    except (OSError, ValueError):
        return default


def load_roi():
    try:
        r = json.loads(ROI_FILE.read_text())
        return int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])
    except (OSError, ValueError, KeyError):
        return None


# ══════════════════════════════════════════════════════════════
#  Telemetry receiver — ring buffer; cũng là cổng gửi PC→ESP32
# ══════════════════════════════════════════════════════════════
class TelemetryReceiver:
    def __init__(self, host=ESP32_HOST, port=ESP32_PORT, buffer_s=1.0):
        self.addr     = (host, port)
        self.buffer_s = buffer_s
        self._buf     = deque()            # [(t_recv, steer, throt, seq, esp_ms, mode)]
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._sock    = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.2)
        self.last_t   = 0.0
        self.rec      = 0
        self.mode     = 0
        self.steer    = 0.0
        self.throt    = 0.0
        self._thread  = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._sock.close()

    def send(self, data: bytes):
        """Gửi PC→ESP32 qua CÙNG socket (để ESP32 luôn gửi telemetry về đây)."""
        try:
            self._sock.sendto(data, self.addr)
        except OSError:
            pass

    def alive(self) -> bool:
        return (time.time() - self.last_t) < 0.5

    def _run(self):
        last_hb = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_hb >= HEARTBEAT_S:
                self.send(b"\x02")                 # heartbeat → ESP32 nhớ IP PC
                last_hb = now
            try:
                data, _ = self._sock.recvfrom(64)
            except (socket.timeout, OSError):
                continue
            if len(data) != TELEM_SIZE:
                continue
            (magic, mode, seq, esp_ms, steer, throt,
             _cs, _ct, _cr, rec) = struct.unpack(TELEM_FMT, data)
            if magic != TELEM_MAGIC:
                continue
            t = time.time()
            with self._lock:
                self._buf.append((t, steer, throt, seq, esp_ms, mode))
                cutoff = t - self.buffer_s
                while self._buf and self._buf[0][0] < cutoff:
                    self._buf.popleft()
                self.last_t, self.rec, self.mode = t, rec, mode
                self.steer, self.throt = steer, throt

    def lookup(self, t_scene: float):
        """(steer, throt, seq, esp_ms) của sample gần t_scene nhất, None nếu rỗng."""
        with self._lock:
            if not self._buf:
                return None
            b = min(self._buf, key=lambda s: abs(s[0] - t_scene))
        return b[1], b[2], b[3], b[4]


# ══════════════════════════════════════════════════════════════
#  Latency tracker — nháy LED trong ROI, đo trễ camera realtime
# ══════════════════════════════════════════════════════════════
class LatencyTracker:
    def __init__(self, roi, send_fn, fallback, period=FLASH_PERIOD):
        self.x, self.y, self.w, self.h = roi
        self.send   = send_fn
        self.fb     = fallback
        self.period = period
        self.thr      = None
        self.base_ema = 0.0                 # nền (LED tắt) — tự cập nhật theo ánh sáng
        self.on_level = 255.0               # mức LED bật (~bão hòa)
        self._lat   = deque(maxlen=7)       # median trượt
        self.state  = "IDLE"
        self.t0     = 0.0
        self.next_flash = 0.0
        self.cool_until = 0.0
        self._new   = None                  # mẫu mới (cho log)

    def spot(self, frame) -> float:
        g = cv2.cvtColor(frame[self.y:self.y+self.h, self.x:self.x+self.w],
                         cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        return float(g.max())

    def calibrate(self, base: float, lit: float) -> bool:
        if lit - base < 15:
            return False
        self.base_ema = base
        self.on_level = lit
        self.thr = (base + lit) / 2.0
        return True

    def observe(self, t_read: float, spot: float):
        if self.thr is None:
            return
        now = time.time()
        if self.state == "IDLE":
            # LED đang tắt → cập nhật nền + ngưỡng theo ánh sáng môi trường realtime
            self.base_ema = 0.95 * self.base_ema + 0.05 * spot
            self.thr = (self.base_ema + self.on_level) / 2.0
            if now >= self.next_flash:
                self.send(LED_ON); self.t0 = now; self.state = "WAIT"
        elif self.state == "WAIT":
            if t_read > self.t0 and spot > self.thr:
                lat = t_read - self.t0
                if 0.0 < lat < 1.0:                 # bỏ outlier
                    self._lat.append(lat); self._new = lat
                self.send(LED_OFF); self.state = "COOL"; self.cool_until = now + 0.4
            elif now - self.t0 > 1.0:               # timeout
                self.send(LED_OFF); self.state = "COOL"; self.cool_until = now + 0.4
        elif self.state == "COOL":
            if now >= self.cool_until:
                self.state = "IDLE"; self.next_flash = now + self.period

    def latency(self) -> float:
        return statistics.median(self._lat) if self._lat else self.fb

    def pop_measurement(self):
        v = self._new; self._new = None
        return v


# ══════════════════════════════════════════════════════════════
#  Session
# ══════════════════════════════════════════════════════════════
class Session:
    def __init__(self, roi):
        self.roi = roi
        self.dir = None
        self.csv_file = self.lat_file = None
        self.csv_writer = self.lat_writer = None
        self.count = 0
        self.active = False

    def start(self, latency):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = DATA_DIR / f"session_{ts}"
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.csv_file = open(self.dir / "actions.csv", "w", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(
            ["frame_idx", "t_pc", "t_scene", "steering", "throttle",
             "latency", "seq", "esp_ms", "mode"])
        self.lat_file = open(self.dir / "latency.csv", "w", newline="")
        self.lat_writer = csv.writer(self.lat_file)
        self.lat_writer.writerow(["t_pc", "latency_ms"])
        (self.dir / "meta.json").write_text(json.dumps({
            "led_roi": {"x": self.roi[0], "y": self.roi[1],
                        "w": self.roi[2], "h": self.roi[3]} if self.roi else None,
            "latency_start": latency, "save_hz": SAVE_HZ, "started": ts,
        }, indent=2))
        self.count = 0
        self.active = True
        print(f"[REC] ● Bắt đầu → {self.dir}", flush=True)

    def save(self, frame, t_pc, t_scene, steer, throt, latency, seq, esp_ms, mode):
        self.count += 1
        cv2.imwrite(str(self.dir / "frames" / f"{self.count:06d}.jpg"),
                    frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        self.csv_writer.writerow([self.count, round(t_pc, 4), round(t_scene, 4),
                                  round(steer, 4), round(throt, 4),
                                  round(latency, 4), seq, esp_ms, mode])

    def log_latency(self, t_pc, lat):
        if self.lat_writer:
            self.lat_writer.writerow([round(t_pc, 4), round(lat * 1000, 1)])

    def stop(self):
        self.active = False
        for f in (self.csv_file, self.lat_file):
            if f:
                f.close()
        self.csv_file = self.lat_file = self.csv_writer = self.lat_writer = None
        print(f"[REC] ○ Kết thúc — {self.count} frames → {self.dir}", flush=True)


# ══════════════════════════════════════════════════════════════
#  HUD
# ══════════════════════════════════════════════════════════════
def draw_overlay(frame, tele, sess, latency_ms, roi):
    out  = frame.copy()
    h, w = out.shape[:2]
    rec  = sess.active
    col  = (0, 0, 255) if rec else (200, 200, 200)
    link = "OK" if tele.alive() else "NO TELEM"
    for i, txt in enumerate([
        f"{'● REC' if rec else '○ STANDBY'}  frame:{sess.count}",
        f"mode:{MODE_NAME.get(tele.mode,'?')}  telem:{link}  lat:{latency_ms:.0f}ms",
        f"steer:{tele.steer:+.2f}  throt:{tele.throt:+.2f}",
    ]):
        cv2.putText(out, txt, (12, 28 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    if roi:
        x, y, ww, hh = roi
        cv2.rectangle(out, (x, y), (x + ww, y + hh), (80, 80, 80), 1)
    cv2.putText(out, "CH10=record  Q/ESC=thoat",
                (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)
    return out


# ══════════════════════════════════════════════════════════════
#  Calibrate tracker threshold (LED off vs on) trước vòng chính
# ══════════════════════════════════════════════════════════════
def calibrate_tracker(cap, tele, tracker) -> bool:
    def spot_over(seconds):
        vals, t0 = [], time.time()
        while time.time() - t0 < seconds:
            f, _ = cap.get_frame_ts(timeout=0.1)
            if f is not None:
                vals.append(tracker.spot(f))
        return statistics.median(vals) if vals else 0.0

    tele.send(LED_OFF); time.sleep(0.3); base = spot_over(0.5)
    tele.send(LED_ON);  time.sleep(0.3); lit  = spot_over(0.5)
    tele.send(LED_OFF)
    ok = tracker.calibrate(base, lit)
    print(f"[CAL] ROI điểm sáng: tắt={base:.0f} bật={lit:.0f} "
          f"(chênh {lit-base:.0f}) → {'OK' if ok else 'FAIL'}", flush=True)
    return ok


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    roi      = load_roi()
    fallback = load_fallback_latency()

    cap  = FrameCapture()
    tele = TelemetryReceiver()
    sess = Session(roi)
    cap.start()
    tele.start()

    tracker = None
    if roi is None:
        print("⚠ Chưa có data/led_roi.json — chạy 'python tools/set_led_roi.py' để bật "
              f"latency realtime. Tạm dùng latency cố định {fallback:.3f}s, KHÔNG mask.",
              flush=True)
    else:
        tracker = LatencyTracker(roi, tele.send, fallback)
        print("Đang calibrate ngưỡng LED...", flush=True)
        if not calibrate_tracker(cap, tele, tracker):
            print("⚠ LED không rõ trong ROI — tắt tracker, dùng latency cố định + KHÔNG mask.",
                  flush=True)
            tracker = None

    cv2.namedWindow("JEPA Recorder — FlySky", cv2.WINDOW_NORMAL)
    print("Sẵn sàng. Gạt CH10 để ghi, Q/ESC thoát.", flush=True)

    save_interval = 1.0 / SAVE_HZ
    last_save = 0.0
    prev_rec  = 0

    try:
        while True:
            frame, t_read = cap.get_frame_ts(timeout=0.05)
            now = time.time()

            # latency realtime + đo sáng ROI cho tracker
            latency = fallback
            if tracker is not None and frame is not None:
                tracker.observe(t_read, tracker.spot(frame))
                latency = tracker.latency()

            # start/stop session theo CH10
            rec = tele.rec if tele.alive() else 0
            if rec and not prev_rec:
                sess.start(latency)
            elif not rec and prev_rec:
                sess.stop()
            prev_rec = rec

            if frame is not None:
                if roi is not None:                       # TÔ ĐEN bbox LED
                    x, y, w, h = roi
                    frame[y:y+h, x:x+w] = 0

                if sess.active:
                    if tracker is not None:
                        m = tracker.pop_measurement()
                        if m is not None:
                            sess.log_latency(now, m)
                    if now - last_save >= save_interval:
                        act = tele.lookup(t_read - latency)
                        if act is not None:
                            steer, throt, seq, esp_ms = act
                            sess.save(frame, now, t_read - latency, steer, throt,
                                      latency, seq, esp_ms, tele.mode)
                        last_save = now

                cv2.imshow("JEPA Recorder — FlySky",
                           draw_overlay(frame, tele, sess, latency * 1000, roi))

            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break

    except KeyboardInterrupt:
        pass
    finally:
        if sess.active:
            sess.stop()
        if tracker is not None:
            tele.send(LED_OFF)
        tele.stop()
        cap.stop()
        cv2.destroyAllWindows()
        print("Done.", flush=True)


if __name__ == "__main__":
    main()
