#!/usr/bin/env python3
"""Bench plumbing test for the closed-loop transport — NO ML, NO graph (works INDOORS).

Verifies the whole action path end-to-end:  PC --TCP--> phone --USB--> ESP32 (AUTO) --> servo,
and the telemetry round-trip back. Use this BEFORE the real inference_loop (which needs the park
graph + GPS). Run it on a STAND with the wheels off the ground.

What it does:
  * acts as the PC server (phone connects, same as pc_stream_view / inference_loop);
  * prints each frame's meta — confirms the UPLINK and the new STATE fields the app now sends
    (speed/lat/lon/gx..gz/ax..az/rx..rz);
  * sends a gentle STEERING SWEEP back (throttle 0 by default) via the phone relay — confirms the
    DOWNLINK + the app's PcLink relay + firmware reading USB control in AUTO;
  * the round-trip check: in AUTO the telemetry ``steering`` echoes the commanded steer, so the
    meta ``steering`` you see should track the value we just sent → the loop is closed.

Setup: car on a stand (wheels up), remote CH9 = AUTO (>1700), phone app open + PC_HOST = this PC.

    PYTHONPATH=src python scripts/bench_relay_test.py            # steer sweep, throttle 0 (safe)
    PYTHONPATH=src python scripts/bench_relay_test.py --throttle 0.08   # tiny ESC pulse (WHEELS UP!)
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot" / "capture"))
import controller as ctl  # noqa: E402


def _recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


class Reader(threading.Thread):
    """Read frames; keep latest meta only (we ignore the JPEG bytes here)."""

    def __init__(self, conn):
        super().__init__(daemon=True)
        self.conn = conn
        self.meta = None
        self.n = 0
        self.alive = True

    def run(self):
        try:
            while self.alive:
                hdr = _recvall(self.conn, 4)
                if not hdr:
                    break
                meta = json.loads(_recvall(self.conn, struct.unpack(">I", hdr)[0]).decode("utf-8"))
                jlen = struct.unpack(">I", _recvall(self.conn, 4))[0]
                if _recvall(self.conn, jlen) is None:
                    break
                self.meta = meta
                self.n += 1
        finally:
            self.alive = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--throttle", type=float, default=0.0, help="constant throttle (default 0; WHEELS UP if >0)")
    ap.add_argument("--steer-amp", type=float, default=0.6, help="steer sweep amplitude")
    ap.add_argument("--hold", type=float, default=1.2, help="seconds per steer step")
    ap.add_argument("--once", action="store_true",
                    help="send each step ONCE (test phone keep-alive: echo phải giữ nguyên suốt step)")
    ap.add_argument("--dongle", action="store_true", help="use ESP-NOW dongle instead of phone relay")
    args = ap.parse_args()

    pattern = [0.0, -args.steer_amp, 0.0, args.steer_amp]   # center, left, center, right
    print(f"[bench] steer sweep {pattern}, throttle {args.throttle:+.2f} "
          f"(throttle clamps to [{ctl.THROTTLE_MIN},{ctl.THROTTLE_MAX}]).")
    if args.throttle != 0.0:
        print("[bench] ⚠️ THROTTLE > 0 — đảm bảo BÁNH KHÔNG CHẠM ĐẤT (kê xe lên giá).")
    print("[bench] remote CH9 = AUTO (>1700). Nếu xe không nhúc nhích: kiểm CH9, app đang mở, USB cắm cổng native.")

    dongle = ctl.SerialDongleSender() if args.dongle else None
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"[bench] listening 0.0.0.0:{args.port} — đặt PC_HOST trong app = IP máy này. Chờ phone…")
    try:
        while True:
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[bench] phone {addr} connected")
            sender = dongle if dongle else ctl.PhoneRelaySender(conn)
            reader = Reader(conn); reader.start()
            i = 0
            try:
                while reader.alive:
                    steer = pattern[i % len(pattern)]
                    i += 1
                    t0 = time.time()
                    if args.once:
                        # GỬI 1 LẦN: dựa vào phone keep-alive resend qua USB. Nếu echo giữ nguyên
                        # suốt step (không tụt về 0) → phone đang tự relay đúng (giải pháp #1 OK).
                        sent = sender.send(steer, args.throttle)
                        while time.time() - t0 < args.hold and reader.alive:
                            time.sleep(0.1)
                    else:
                        # GỬI LẶP ~10Hz suốt step (PC tự keep-alive — không phụ thuộc phone relay).
                        sent = True
                        while time.time() - t0 < args.hold and reader.alive:
                            sent = sender.send(steer, args.throttle) and sent
                            time.sleep(0.1)
                    m = reader.meta or {}
                    echo = m.get("steering", "?")
                    print(f"[bench] sent steer{steer:+.2f} throt{args.throttle:+.2f} "
                          f"{'ok' if sent else 'SEND-FAIL'} | phone frames={reader.n} "
                          f"mode={m.get('mode','?')} echo_steer={echo} echo_throt={m.get('throttle','-')} "
                          f"speed={m.get('speed','-')} gz={m.get('gz','-')}", flush=True)
                    if isinstance(echo, (int, float)) and abs(float(echo) - steer) < 0.1 and m.get("mode") == 2:
                        print("[bench]   ✓ round-trip khớp (telemetry phản hồi đúng steer đã gửi, mode=AUTO)")
            except Exception as e:
                print(f"[bench] err: {e}")
            finally:
                reader.alive = False
                try:
                    sender.send(0.0, 0.0)
                except Exception:
                    pass
                conn.close()
                print("[bench] phone disconnected; chờ lại…")
    except KeyboardInterrupt:
        print("\n[bench] bye")
    finally:
        if dongle:
            dongle.stop(); dongle.close()
        srv.close()


if __name__ == "__main__":
    main()
