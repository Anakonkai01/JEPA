"""
Helper gửi lệnh PC→xe qua dongle ESP-NOW (USB serial) — dùng chung cho các tool
cần bật/tắt LED (set_led_roi.py, measure_latency.py).

Mỗi dòng trên dây serial = hex + '\\n' (dongle giải mã → esp_now_send tới xe). Thay cho
UDP cũ (192.168.1.23:4210) đã bỏ khi chuyển sang ESP-NOW.

Gotcha: mở cổng USB-CDC bật DTR → ESP32-S3 dongle reset & boot lại (~1.8s). Lệnh gửi trong
lúc này sẽ mất → Dongle.__init__ chờ boot xong; ngoài ra ESP-NOW unicast có thể rớt gói nên
nơi gọi nên gửi lại LED_ON định kỳ.
"""

import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[2]                 # repo root (robot/tools/ -> JEPA/)
sys.path.insert(0, str(ROOT / "robot" / "capture"))        # recorder.py lives here
from recorder import autodetect_port, SERIAL_PORT, SERIAL_BAUD  # noqa: E402

BOOT_WAIT = 1.8


def resolve_port(argv_idx: int = 1) -> str:
    """Cổng dongle: sys.argv[argv_idx] > 'auto'. 'auto'/không truyền = tự dò /dev/ttyACM*."""
    port = sys.argv[argv_idx] if len(sys.argv) > argv_idx else "auto"
    if port == "auto":
        found = autodetect_port()
        if found:
            print(f"[serial] auto-detect dongle → {found}", flush=True)
            return found
        print(f"[serial] auto-detect THẤT BẠI — dùng {SERIAL_PORT} (cắm dongle + bật xe chưa?)",
              flush=True)
        return SERIAL_PORT
    return port


class Dongle:
    """Mở dongle serial, chờ boot, gửi byte tới xe (hex+'\\n')."""

    def __init__(self, port: str):
        self._ser = serial.Serial(port, SERIAL_BAUD, timeout=0.2)
        time.sleep(BOOT_WAIT)                      # chờ ESP32-S3 dongle reset & boot
        try:
            self._ser.reset_input_buffer()
        except OSError:
            pass

    def send(self, data: bytes):
        try:
            self._ser.write(data.hex().encode("ascii") + b"\n")
        except (OSError, serial.SerialException):
            pass

    def close(self):
        try:
            self._ser.close()
        except OSError:
            pass
