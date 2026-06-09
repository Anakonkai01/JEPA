"""Controller transport — encode a float action [steer, throttle] to the 2-byte ESP32
command and ship it to the car (Phase 4 / closed-loop).

Replaces the old UDP socket (the car has no IP — it's ESP-NOW/USB). Two transports:

  * ``PhoneRelaySender``  — PC → phone (over the live TCP socket) → ESP32 (phone writes
    the bytes to USB). This is the CHOSEN path: the phone is the onboard camera AND the
    USB link to the ESP32, so the action rides back down the same connection the frames
    came up. Needs the Android app's PcLink downlink relay (see robot/android).
  * ``SerialDongleSender`` — PC → ESP-NOW dongle on /dev/ttyACM* → ESP32, writing
    ``hex+\n`` exactly like ``recorder.py``'s ``send``. Fallback if you plug the dongle
    into the PC instead of routing through the phone.

Byte mapping (ESC Mode 3, recalib 2026-06-07, see CLAUDE.md / firmware/specs.md):
  steer  ∈ [-1, 1]                       -> byte (steer+1)/2 * 255   (0=left,127=center,255=right)
  throt  ∈ [THROTTLE_MIN, THROTTLE_MAX]  -> byte (throt+1)/2 * 255   (symmetric; 127=neutral)
Throttle is HARD-CLAMPED to the car's safe envelope [-0.16, 0.15] before encoding.
"""
from __future__ import annotations

import glob
import struct

# Safe throttle envelope of THIS car (Mode-3 linear ESC). Match CEMPlannerAC's box.
THROTTLE_MIN = -0.16
THROTTLE_MAX = 0.15
ACTION_MAGIC = 0xA5          # downlink frame marker PC -> phone (3 bytes: magic, steer, throt)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def action_to_bytes(steer: float, throttle: float) -> bytes:
    """Float [steer, throttle] -> 2 raw bytes for the ESP32 (with clamps + Mode-3 map)."""
    steer = _clamp(float(steer), -1.0, 1.0)
    throttle = _clamp(float(throttle), THROTTLE_MIN, THROTTLE_MAX)
    steer_b = _clamp(int((steer + 1.0) / 2.0 * 255), 0, 255)
    throt_b = _clamp(int((throttle + 1.0) / 2.0 * 255), 0, 255)   # symmetric (Mode 3 direct reverse)
    return struct.pack("BB", steer_b, throt_b)


def framed_action(steer: float, throttle: float) -> bytes:
    """3-byte downlink frame ``[ACTION_MAGIC, steer_b, throt_b]`` for the phone relay.
    The phone checks the magic, strips it, and writes the 2 control bytes to the ESP32."""
    return bytes([ACTION_MAGIC]) + action_to_bytes(steer, throttle)


class PhoneRelaySender:
    """Write the action back down the live phone TCP socket (PC -> phone -> ESP32).

    ``sock`` is the connection accepted from the phone (the same one frames arrive on).
    Non-fatal on error (a dropped link just means the car's AUTO-loss watchdog neutralises;
    >500 ms without control -> neutral in firmware)."""

    def __init__(self, sock):
        self.sock = sock

    def send(self, steer: float, throttle: float) -> bool:
        try:
            self.sock.sendall(framed_action(steer, throttle))
            return True
        except OSError:
            return False

    def stop(self):
        self.send(0.0, 0.0)          # neutral (steer center, throttle 0 -> 127/127)


class SerialDongleSender:
    """PC -> ESP-NOW dongle (/dev/ttyACM*) -> ESP32, writing hex+'\\n' like recorder.py."""

    BAUD = 115200

    def __init__(self, port: str | None = None):
        import serial  # lazy: only the dongle path needs pyserial
        if port in (None, "auto"):
            ports = sorted(glob.glob("/dev/ttyACM*"))
            if not ports:
                raise OSError("no /dev/ttyACM* — plug in the ESP-NOW dongle")
            port = ports[0]
        self._ser = serial.Serial(port, self.BAUD, timeout=0.2)
        self.port = port

    def send(self, steer: float, throttle: float) -> bool:
        try:
            self._ser.write(action_to_bytes(steer, throttle).hex().encode("ascii") + b"\n")
            return True
        except OSError:
            return False

    def stop(self):
        self.send(0.0, 0.0)

    def close(self):
        try:
            self._ser.close()
        except OSError:
            pass


if __name__ == "__main__":
    # Quick byte-map sanity check (no hardware).
    for s, t in [(0.0, 0.0), (-1.0, 0.15), (1.0, -0.16), (0.5, 0.5)]:
        b = action_to_bytes(s, t)
        print(f"steer {s:+.2f} throt {t:+.2f} -> bytes {b[0]:3d} {b[1]:3d}  (throt clamped to [{THROTTLE_MIN},{THROTTLE_MAX}])")
