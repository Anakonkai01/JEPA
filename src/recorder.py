"""
Data collection (FlySky i-BUS) — xe do FlySky lái, PC ghi THỤ ĐỘNG,
latency được đo REALTIME bằng LED gắn cố định trong khung hình.

Luồng:
  ESP32 (mode RECORD) gửi telemetry @50Hz qua ESP-NOW → dongle → serial hex
  RunCam → WFB-NG → ffmpeg → (frame BGR, t_read)  (capture.py)
  recorder:
    • TelemetryReceiver: đọc serial → ring buffer ~1s; gửi lệnh LED/AUTO; đọc RSSI ESP-NOW
    • WfbStatsReader: tail log wfb_rx → RSSI camera + packet loss
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
import glob
import struct
import statistics
import threading
from collections import deque
from pathlib import Path
from datetime import datetime

import cv2
import serial

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from capture import FrameCapture

# ── Cấu hình ──────────────────────────────────────────────────
DATA_DIR     = ROOT / "data" / "raw"
ROI_FILE     = ROOT / "data" / "led_roi.json"
LAT_FILE     = ROOT / "data" / "camera_latency.txt"
JPEG_QUALITY = 90
SAVE_HZ      = 10

# Dongle ESP-NOW↔serial. Override: argv[1] hoặc env JEPA_SERIAL ("auto" = tự dò ttyACM*).
SERIAL_PORT  = "/dev/ttyACM0"
SERIAL_BAUD  = 115200

# Log stats WFB-NG (wfb_up.sh tee stdout của wfb_rx vào đây) → RSSI camera + packet loss.
WFB_STATS_LOG = "/tmp/jepa_wfb_stats.log"

FLASH_PERIOD = 2.0           # tracker nháy LED mỗi 2s
LED_ON, LED_OFF = b"\x01", b"\x00"

# Chống nháy ảo ngoài nắng: latency vật lý của đường truyền (H.265+WFB+decode)
# không thể < ~40ms — đo trong bóng cho ~88–117ms. Mọi giá trị ngoài [MIN,MAX] = ảo, bỏ.
LAT_MIN, LAT_MAX = 0.040, 0.600
# LED phải làm điểm sáng ROI vọt lên ÍT NHẤT chừng này (gray level) so với nền ngay
# trước khi bật. Nền (nắng) đã sáng tới mức không còn đủ "khoảng trống" → bỏ nháy, báo SUN.
RISE_MIN = 30.0

# Telemetry @50Hz = 20ms/sample. Khi telemetry rớt (xa/yếu), sample khớp gần t_scene nhất
# sẽ cách xa hơn nhiều → action ôi. Lệch > ngưỡng này ⇒ BỎ frame (không ghép action sai).
MATCH_TOL = 0.050            # 50ms ≈ 2.5 sample

# Telemetry struct (khớp firmware, little-endian, packed):
#   magic B|mode B|seq I|esp_ms I|steering f|throttle f|ch_steer H|ch_throt H|ch_record H|rec B
TELEM_FMT   = "<BBIIffHHHB"
TELEM_SIZE  = struct.calcsize(TELEM_FMT)   # 25
TELEM_MAGIC = 0xAC
MODE_NAME   = {0: "NEUTRAL", 1: "RECORD", 2: "AUTO"}


def autodetect_port(timeout=2.0):
    """Quét /dev/ttyACM* tìm cổng phát ra frame telemetry hợp lệ (0xAC). None nếu không thấy."""
    for port in sorted(glob.glob("/dev/ttyACM*")):
        try:
            with serial.Serial(port, SERIAL_BAUD, timeout=0.2) as s:
                buf, t0 = bytearray(), time.time()
                while time.time() - t0 < timeout:
                    buf.extend(s.read(s.in_waiting or 1) or b"")
                    while b"\n" in buf:
                        nl = buf.find(b"\n")
                        line = bytes(buf[:nl]).strip(); del buf[:nl + 1]
                        try:
                            d = bytes.fromhex(line.decode("ascii"))
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if len(d) >= TELEM_SIZE and d[0] == TELEM_MAGIC:
                            return port
        except (OSError, serial.SerialException):
            continue
    return None


def resolve_port():
    """Cổng dongle: argv[1] > env JEPA_SERIAL > mặc định. Giá trị 'auto' = tự dò."""
    port = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("JEPA_SERIAL") or SERIAL_PORT
    if port == "auto":
        found = autodetect_port()
        if found:
            print(f"[serial] auto-detect → {found}", flush=True)
            return found
        print(f"[serial] auto-detect THẤT BẠI — dùng {SERIAL_PORT}", flush=True)
        return SERIAL_PORT
    return port


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
    def __init__(self, port=SERIAL_PORT, baud=SERIAL_BAUD, buffer_s=1.0):
        self.buffer_s = buffer_s
        self._buf     = deque()            # [(t_recv, steer, throt, seq, esp_ms, mode)]
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._rxbuf   = bytearray()        # gom byte serial tới '\n'
        self._ser     = serial.Serial(port, baud, timeout=0.2)
        self.last_t   = 0.0
        self.rec      = 0
        self.mode     = 0
        self.steer    = 0.0
        self.throt    = 0.0
        self.rssi     = None               # RSSI ESP-NOW (dBm) — dongle gắn vào byte 26
        self._raw     = deque()            # stream 50Hz THÔ chờ ghi telemetry.csv (re-align offline)
        self._thread  = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._ser.close()
        except OSError:
            pass

    def send(self, data: bytes):
        """Gửi PC→xe: hex + newline → dongle giải mã → esp_now_send. (LED/AUTO không đổi phía gọi.)"""
        try:
            self._ser.write(data.hex().encode("ascii") + b"\n")
        except (OSError, serial.SerialException):
            pass

    def alive(self) -> bool:
        return (time.time() - self.last_t) < 0.5

    def _run(self):
        while not self._stop.is_set():
            try:
                if not self._ser.is_open:
                    break
                chunk = self._ser.read(self._ser.in_waiting or 1)
            except (OSError, serial.SerialException, TypeError):
                break          # stop() đóng cổng giữa lúc đọc → fd=None → TypeError, thoát êm
            if not chunk:
                continue
            self._rxbuf.extend(chunk)
            while True:
                nl = self._rxbuf.find(b"\n")
                if nl < 0:
                    break
                line = bytes(self._rxbuf[:nl]).strip()
                del self._rxbuf[:nl + 1]
                if not line:
                    continue
                try:
                    data = bytes.fromhex(line.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    continue                       # dòng debug người-đọc / hỏng → bỏ
                if len(data) < TELEM_SIZE:
                    continue
                (magic, mode, seq, esp_ms, steer, throt,
                 _cs, _ct, _cr, rec) = struct.unpack(TELEM_FMT, data[:TELEM_SIZE])
                if magic != TELEM_MAGIC:
                    continue
                # byte 26 (nếu có) = RSSI ESP-NOW int8 dBm (dongle gắn vào)
                rssi = (int.from_bytes(data[TELEM_SIZE:TELEM_SIZE + 1], "little", signed=True)
                        if len(data) > TELEM_SIZE else None)
                t = time.time()
                with self._lock:
                    self._buf.append((t, steer, throt, seq, esp_ms, mode))
                    cutoff = t - self.buffer_s
                    while self._buf and self._buf[0][0] < cutoff:
                        self._buf.popleft()
                    self._raw.append((t, seq, esp_ms, steer, throt, mode))
                    self.last_t, self.rec, self.mode = t, rec, mode
                    self.steer, self.throt = steer, throt
                    if rssi is not None:
                        self.rssi = rssi

    def lookup(self, t_scene: float):
        """(steer, throt, seq, esp_ms, t_recv) của sample gần t_scene nhất, None nếu rỗng.
        t_recv (đồng hồ PC) để bên gọi đo độ lệch ghép cặp → bỏ frame khi telemetry rớt."""
        with self._lock:
            if not self._buf:
                return None
            b = min(self._buf, key=lambda s: abs(s[0] - t_scene))
        return b[1], b[2], b[3], b[4], b[0]

    def drain_raw(self):
        """Lấy & xoá toàn bộ sample 50Hz thô tích luỹ (để main loop ghi telemetry.csv)."""
        with self._lock:
            out = list(self._raw)
            self._raw.clear()
        return out


# ══════════════════════════════════════════════════════════════
#  WFB-NG stats — tail log của wfb_rx → RSSI camera + packet loss
#    Format (mỗi ~1s, wfb_up.sh tee stdout wfb_rx vào WFB_STATS_LOG):
#      <ts>\tRX_ANT\t<freq:mcs:bw>\t<ant>\t<count:rssi_min:rssi_avg:rssi_max:snr...>
#      <ts>\tPKT\t<p_all:b_all:dec_err:dec_ok:fec_rec:p_lost:p_bad:...>
# ══════════════════════════════════════════════════════════════
class WfbStatsReader:
    def __init__(self, path=WFB_STATS_LOG):
        self.path     = path
        self.rssi     = None     # rssi_avg (dBm)
        self.rssi_min = None
        self.recv     = 0        # dec_ok / interval
        self.lost     = 0        # p_lost / interval
        self.last_t   = 0.0
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def alive(self) -> bool:
        return (time.time() - self.last_t) < 3.0

    def _parse(self, line: str):
        p = line.rstrip("\n").split("\t")
        if len(p) < 3:
            return
        seg = p[-1].split(":")
        try:
            if p[1] == "RX_ANT" and len(seg) >= 4:
                self.rssi_min, self.rssi = int(seg[1]), int(seg[2])
                self.last_t = time.time()
            elif p[1] == "PKT" and len(seg) >= 6:
                self.recv, self.lost = int(seg[3]), int(seg[5])
                self.last_t = time.time()
        except (ValueError, IndexError):
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                with open(self.path, "r") as f:
                    f.seek(0, 2)                     # nhảy tới cuối — chỉ đọc dòng mới
                    while not self._stop.is_set():
                        line = f.readline()
                        if not line:
                            time.sleep(0.2); continue
                        self._parse(line)
            except OSError:
                time.sleep(0.5)                      # file chưa có (camera chưa lên) → thử lại


# ══════════════════════════════════════════════════════════════
#  FPS meter — FPS thực + độ tươi frame (phát hiện camera đứng)
# ══════════════════════════════════════════════════════════════
class FpsMeter:
    def __init__(self, n=30):
        self._t     = deque(maxlen=n)
        self.last_t = 0.0

    def tick(self, t):
        self._t.append(t); self.last_t = t

    def fps(self) -> float:
        if len(self._t) < 2:
            return 0.0
        span = self._t[-1] - self._t[0]
        return (len(self._t) - 1) / span if span > 0 else 0.0

    def age(self, now) -> float:
        return now - self.last_t if self.last_t else 999.0


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
        self.pre    = 0.0                   # nền ngay TRƯỚC nháy (baseline đồng bộ)
        self.next_flash = 0.0
        self.cool_until = 0.0
        self._new   = None                  # mẫu mới (cho log)
        self.last_measure_t = 0.0           # mốc đo thành công gần nhất (chỉ cho HUD)
        self.last_sat_t     = 0.0           # mốc bỏ nháy gần nhất vì nền bão hoà (nắng)
        self.n_reject       = 0             # số lần bắt được "LED" nhưng latency ngoài [MIN,MAX] (ảo)

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
            # LED đang tắt → cập nhật nền theo ánh sáng môi trường realtime.
            self.base_ema = 0.95 * self.base_ema + 0.05 * spot
            headroom = self.on_level - self.base_ema
            # Ngưỡng = nền + bước nhảy tối thiểu (tương đối, KHÔNG dùng mức tuyệt đối) →
            # nắng nâng nền lên thì ngưỡng cũng nâng theo, không bắt nhầm.
            self.thr = self.base_ema + max(RISE_MIN, 0.5 * headroom)
            if now >= self.next_flash:
                self.pre = self.base_ema
                if headroom < RISE_MIN:
                    # Nền đã sáng sát mức LED (nắng gắt) → LED không thể tách khỏi nền.
                    # Bỏ nháy này, đánh dấu SUN; latency() sẽ tự rơi về fallback/median cũ.
                    self.last_sat_t = now
                    self.next_flash = now + self.period
                else:
                    self.send(LED_ON); self.t0 = now; self.state = "WAIT"
        elif self.state == "WAIT":
            # Chỉ chấp nhận khi điểm sáng VỌT so với nền-ngay-trước (đồng bộ với lệnh bật).
            if t_read > self.t0 and spot >= self.thr and spot - self.pre >= RISE_MIN:
                lat = t_read - self.t0
                if LAT_MIN <= lat <= LAT_MAX:            # latency vật lý hợp lệ
                    self._lat.append(lat); self._new = lat
                    self.last_measure_t = now
                else:                                    # quá nhanh/chậm = ảo (nắng) → bỏ
                    self.n_reject += 1
                self.send(LED_OFF); self.state = "COOL"; self.cool_until = now + 0.4
            elif now - self.t0 > 1.0:                    # timeout (không thấy LED vọt lên)
                self.send(LED_OFF); self.state = "COOL"; self.cool_until = now + 0.4
        elif self.state == "COOL":
            if now >= self.cool_until:
                self.state = "IDLE"; self.next_flash = now + self.period

    def latency(self) -> float:
        return statistics.median(self._lat) if self._lat else self.fb

    def pop_measurement(self):
        v = self._new; self._new = None
        return v

    def status(self, now, spot):
        """(nhãn, chi tiết) cho HUD — vì sao latency đang cập nhật được hay không."""
        if self.thr is None:
            return ("OFF", "chua calib")
        # Nền bão hoà (nắng) trong ~6s gần đây → LED không tách được, đang dùng fallback.
        if self.last_sat_t and now - self.last_sat_t < 3 * self.period:
            return ("SUN", f"nen bao hoa {self.base_ema:.0f}>=on{self.on_level:.0f}-{RISE_MIN:.0f} -> fallback")
        if self.last_measure_t == 0:
            tail = f"  (bo {self.n_reject} gt ao)" if self.n_reject else ""
            return ("DO", f"chua thay LED  spot{spot:.0f}/thr{self.thr:.0f}{tail}")
        age = now - self.last_measure_t
        if age > 3 * self.period:               # >~6s không đo được → LED khuất/ngoài ROI
            return ("STALE", f"{age:.0f}s ko thay LED  spot{spot:.0f}/thr{self.thr:.0f}")
        return ("LIVE", f"n{len(self._lat)} {age:.0f}s truoc")


# ══════════════════════════════════════════════════════════════
#  Session
# ══════════════════════════════════════════════════════════════
class Session:
    def __init__(self, roi):
        self.roi = roi
        self.dir = None
        self.csv_file = self.lat_file = self.tel_file = None
        self.csv_writer = self.lat_writer = self.tel_writer = None
        self.count = 0
        self.skipped = 0           # frame bị bỏ vì telemetry rớt (ghép cặp không tin được)
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
        # Stream telemetry 50Hz THÔ — để re-align offline với L_cam bất kỳ (không phụ thuộc
        # giá trị latency lúc thu). t_recv = đồng hồ PC; esp_ms = đồng hồ ESP32.
        self.tel_file = open(self.dir / "telemetry.csv", "w", newline="")
        self.tel_writer = csv.writer(self.tel_file)
        self.tel_writer.writerow(["t_recv", "seq", "esp_ms", "steering", "throttle", "mode"])
        (self.dir / "meta.json").write_text(json.dumps({
            "led_roi": {"x": self.roi[0], "y": self.roi[1],
                        "w": self.roi[2], "h": self.roi[3]} if self.roi else None,
            "latency_start": latency, "save_hz": SAVE_HZ, "started": ts,
            "match_tol": MATCH_TOL,
        }, indent=2))
        self.count = 0
        self.skipped = 0
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

    def log_telem(self, samples):
        if not self.tel_writer:
            return
        for t_recv, seq, esp_ms, steer, throt, mode in samples:
            self.tel_writer.writerow([round(t_recv, 4), seq, esp_ms,
                                      round(steer, 4), round(throt, 4), mode])

    def stop(self):
        self.active = False
        for f in (self.csv_file, self.lat_file, self.tel_file):
            if f:
                f.close()
        self.csv_file = self.lat_file = self.tel_file = None
        self.csv_writer = self.lat_writer = self.tel_writer = None
        print(f"[REC] ○ Kết thúc — {self.count} frames "
              f"(bỏ {self.skipped} vì telemetry rớt) → {self.dir}", flush=True)


# ══════════════════════════════════════════════════════════════
#  HUD
# ══════════════════════════════════════════════════════════════
GREEN, RED, GRAY, YELLOW, WHITE = (0, 220, 0), (0, 0, 255), (190, 190, 190), (0, 210, 255), (255, 255, 255)


def draw_overlay(frame, tele, sess, latency_ms, lat_status, cam, wfb, roi, scale=2):
    """Phóng to ×scale để chữ to/nét; frame LƯU vẫn là frame gốc (overlay chỉ để hiển thị)."""
    h0, w0 = frame.shape[:2]
    out = cv2.resize(frame, (w0 * scale, h0 * scale), interpolation=cv2.INTER_NEAREST)
    now = time.time()

    def put(txt, row, col, sz=0.6):
        cv2.putText(out, txt, (12, 32 + row * 30),
                    cv2.FONT_HERSHEY_SIMPLEX, sz, col, 2, cv2.LINE_AA)

    rec = sess.active
    skip = f"  skip:{sess.skipped}" if sess.skipped else ""
    put(f"{'[REC]' if rec else '[STANDBY]'}  frame:{sess.count}{skip}", 0, RED if rec else GRAY, 0.7)

    # telemetry ESP-NOW + RSSI
    tok = tele.alive()
    esp = f"{tele.rssi}dBm" if tele.rssi is not None else "--"
    put(f"mode:{MODE_NAME.get(tele.mode,'?')}  telem:{'OK' if tok else 'NO TELEM'}  ESP:{esp}",
        1, GREEN if tok else RED)

    put(f"steer:{tele.steer:+.2f}  throt:{tele.throt:+.2f}", 2, WHITE)

    # latency + trạng thái LED tracker
    st, detail = lat_status
    stcol = {"LIVE": GREEN, "DO": YELLOW, "STALE": RED, "SUN": RED, "OFF": GRAY}.get(st, GRAY)
    put(f"lat:{latency_ms:.0f}ms  LED:{st} ({detail})", 3, stcol, 0.55)

    # camera: FPS + độ tươi frame (đo phía recorder)
    fps, age = cam.fps(), cam.age(now)
    camcol = GREEN if (fps > 0 and age < 0.5) else RED
    put(f"CAM:{fps:.0f}fps  age:{age*1000:.0f}ms", 4, camcol, 0.55)

    # camera: RSSI + packet loss (từ WFB-NG)
    if wfb is not None and wfb.alive() and wfb.rssi is not None:
        tot = wfb.recv + wfb.lost
        lossp = (100.0 * wfb.lost / tot) if tot else 0.0
        wcol = GREEN if (wfb.rssi > -80 and lossp < 5) else (YELLOW if lossp < 20 else RED)
        put(f"WFB:{wfb.rssi}dBm  loss:{wfb.lost} ({lossp:.0f}%)", 5, wcol, 0.55)
    else:
        put("WFB: no log (chay wfb_up.sh ban moi)", 5, GRAY, 0.55)

    if roi:
        x, y, ww, hh = (v * scale for v in roi)
        cv2.rectangle(out, (x, y), (x + ww, y + hh), (80, 80, 80), 1)
    cv2.putText(out, "CH10=record   F=fullscreen   Q/ESC=thoat",
                (12, out.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRAY, 1, cv2.LINE_AA)
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

    port = resolve_port()
    try:
        tele = TelemetryReceiver(port=port)
    except (OSError, serial.SerialException) as e:
        ports = ", ".join(sorted(glob.glob("/dev/ttyACM*"))) or "(không có)"
        print(f"✗ Không mở được serial {port}: {e}\n"
              f"  Cổng đang có: {ports}\n"
              f"  Cắm dongle chưa? Thử: python recorder.py auto", flush=True)
        sys.exit(1)
    cap  = FrameCapture()
    cam  = FpsMeter()
    wfb  = WfbStatsReader()
    sess = Session(roi)
    cap.start()
    tele.start()
    wfb.start()

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

    WIN = "JEPA Recorder — FlySky"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1280, 760)
    fullscreen = False
    print("Sẵn sàng. Gạt CH10 để ghi, F=fullscreen, Q/ESC thoát.", flush=True)

    save_interval = 1.0 / SAVE_HZ
    last_save = 0.0
    prev_rec  = 0

    try:
        while True:
            frame, t_read = cap.get_frame_ts(timeout=0.05)
            now = time.time()
            if frame is not None:
                cam.tick(t_read)

            # latency realtime + đo sáng ROI cho tracker (tính spot 1 lần)
            latency = fallback
            spot = 0.0
            if frame is not None and tracker is not None:
                spot = tracker.spot(frame)
                tracker.observe(t_read, spot)
                latency = tracker.latency()
            lat_status = tracker.status(now, spot) if tracker is not None else ("OFF", "no tracker")

            # start/stop session theo CH10
            rec = tele.rec if tele.alive() else 0
            if rec and not prev_rec:
                sess.start(latency)
            elif not rec and prev_rec:
                sess.stop()
            prev_rec = rec

            # Telemetry raw 50Hz: REC → ghi mọi vòng (kể cả frame None, không thủng stream);
            # standby → xả-bỏ để session sau không dính backlog.
            if sess.active:
                sess.log_telem(tele.drain_raw())
            else:
                tele.drain_raw()

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
                        t_scene = t_read - latency
                        act = tele.lookup(t_scene)
                        if act is not None and abs(act[4] - t_scene) <= MATCH_TOL:
                            steer, throt, seq, esp_ms, _ = act
                            sess.save(frame, now, t_scene, steer, throt,
                                      latency, seq, esp_ms, tele.mode)
                        else:                              # telemetry rớt → action ôi, bỏ frame
                            sess.skipped += 1
                        last_save = now

                cv2.imshow(WIN, draw_overlay(frame, tele, sess, latency * 1000,
                                             lat_status, cam, wfb, roi))

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("f"):
                fullscreen = not fullscreen
                cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)

    except KeyboardInterrupt:
        pass
    finally:
        if sess.active:
            sess.stop()
        if tracker is not None:
            tele.send(LED_OFF)
        tele.stop()
        wfb.stop()
        cap.stop()
        cv2.destroyAllWindows()
        print("Done.", flush=True)


if __name__ == "__main__":
    main()
