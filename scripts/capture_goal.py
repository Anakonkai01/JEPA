#!/usr/bin/env python3
"""Capture a GOAL image from the phone's live stream — for setting a navigation goal in the field.

ViNG-style goal setting: drive the car (manually) to the DESTINATION, run this to grab the current
view as the goal image, drive the car back to the start, then run ``inference_loop.py --goal-image``
to autonomously navigate to that destination.

The phone is the TCP client (same stream as pc_stream_view / inference_loop); this is the server.
It saves the Nth received frame (``--skip`` lets the auto-exposure settle) and exits.

    PYTHONPATH=src python scripts/capture_goal.py --out data/goal.jpg
"""
from __future__ import annotations

import argparse
import socket
import struct
from pathlib import Path


def _recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/goal.jpg")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--skip", type=int, default=15, help="bỏ N frame đầu cho cam ổn định rồi mới chụp")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"[capture] nghe 0.0.0.0:{args.port} — lái xe TỚI ĐÍCH, để app stream về. Chờ phone…")
    conn, addr = srv.accept()
    print(f"[capture] phone {addr} nối — chụp frame thứ {args.skip}…")
    n = 0
    try:
        while True:
            hdr = _recvall(conn, 4)
            if not hdr:
                print("[capture] mất kết nối trước khi chụp được"); return
            _recvall(conn, struct.unpack(">I", hdr)[0])                 # meta (bỏ)
            jpg = _recvall(conn, struct.unpack(">I", _recvall(conn, 4))[0])
            if jpg is None:
                print("[capture] mất kết nối"); return
            n += 1
            if n >= args.skip:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                with open(args.out, "wb") as f:
                    f.write(jpg)
                print(f"[capture] ✓ đã lưu goal: {args.out} ({len(jpg)} bytes, frame #{n}). "
                      f"Giờ đem xe VỀ điểm xuất phát rồi chạy:")
                print(f"          PYTHONPATH=src python scripts/inference_loop.py --goal-image {args.out}")
                return
    finally:
        conn.close(); srv.close()


if __name__ == "__main__":
    main()
