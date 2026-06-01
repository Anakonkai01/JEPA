"""
UDP controller — gửi 2-byte command tới ESP32-S3.

Protocol:
  byte[0]  steering : 0=full-left  127=center  255=full-right
  byte[1]  throttle : 127=neutral  255=full-fwd  (< 127 → neutral on ESP32)

Input floats: steering in [-1, 1], throttle in [0, 1].
"""

import socket
import struct

ESP32_HOST = "192.168.1.23"
ESP32_PORT = 4210


class ESPController:
    def __init__(self, host: str = ESP32_HOST, port: int = ESP32_PORT):
        self.addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # ------------------------------------------------------------------
    def send(self, steering: float, throttle: float):
        """
        steering : [-1, 1]  — negative = left, positive = right
        throttle : [-1, 1]  — >0 = tiến, <0 = lùi (byte<64), 0 = neutral
        """
        steer_b = self._to_byte(steering)   # -1→0  0→127  1→255
        if throttle >= 0:
            throttle_b = 127 + int(throttle * 128)
            throttle_b = min(255, throttle_b)
        else:
            # Lùi: map [-1, 0) → [0, 63] (firmware nhận < 64 → muốn reverse)
            throttle_b = int((1.0 + throttle) * 63)
            throttle_b = max(0, min(63, throttle_b))
        self._sock.sendto(struct.pack("BB", steer_b, throttle_b), self.addr)

    def stop(self):
        """Gửi neutral ngay lập tức."""
        self._sock.sendto(struct.pack("BB", 127, 127), self.addr)

    def close(self):
        self._sock.close()

    # ------------------------------------------------------------------
    @staticmethod
    def _to_byte(value: float) -> int:
        """Map [-1, 1] → [0, 255]."""
        b = int((value + 1.0) / 2.0 * 255)
        return max(0, min(255, b))

    # ------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop()
        self.close()


# ------------------------------------------------------------------
# Quick test
# ------------------------------------------------------------------
if __name__ == "__main__":
    import time

    with ESPController() as ctrl:
        print("Tiến thẳng 2 giây...")
        ctrl.send(steering=0.0, throttle=0.25)
        time.sleep(2.0)

        print("Quẹo trái 1 giây...")
        ctrl.send(steering=-0.6, throttle=0.25)
        time.sleep(1.0)

        print("Dừng.")
        ctrl.stop()
