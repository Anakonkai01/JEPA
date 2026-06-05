#!/usr/bin/env python3
"""Nhận frame JPEG + meta JSON từ app điện thoại (PcLink) qua TCP → hiện LIVE (cv2) + tùy chọn lưu.

App điện thoại là client, máy này là server. Đặt PC_HOST trong app = IP máy này:
  - cùng LAN: `hostname -I`
  - qua Tailscale (phone 5G, PC ở nhà): IP 100.x.x.x của máy này (`tailscale ip -4`)

Chạy:
  conda activate ai
  python tools/pc_stream_view.py             # chỉ xem live
  python tools/pc_stream_view.py --save      # xem live + lưu bản sao vào data/raw/pc_<ts>/ khi app REC
  python tools/pc_stream_view.py --port 5055

LƯU Ý: bản lưu ở đây chỉ là COPY tiện (frames + actions.csv). Dataset chuẩn (có telemetry.csv
50Hz + cảm biến cho sync.py) vẫn lấy từ điện thoại bằng `adb pull`. Bấm 'q' trên cửa sổ để thoát.
"""
import argparse
import json
import os
import socket
import struct
from datetime import datetime

import cv2
import numpy as np


def recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def handle_conn(conn, save):
    sess_dir = None
    actions = None
    n = 0
    nrecv = 0
    while True:
        hdr = recvall(conn, 4)
        if not hdr:
            break
        meta = json.loads(recvall(conn, struct.unpack(">I", hdr)[0]).decode("utf-8"))
        jpg = recvall(conn, struct.unpack(">I", recvall(conn, 4))[0])
        if jpg is None:
            break
        nrecv += 1
        if nrecv == 1 or nrecv % 30 == 0:
            print("[pc_stream] đã nhận %d frame (steer %+.2f throt %+.2f)" % (
                nrecv, meta.get("steering", 0.0), meta.get("throttle", 0.0)))

        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            hud = "steer %+.2f  throt %+.2f  mode %s  %s" % (
                meta.get("steering", 0.0), meta.get("throttle", 0.0),
                meta.get("mode", "?"), "REC" if meta.get("recording") else "standby")
            cv2.putText(img, hud, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 0, 255) if meta.get("recording") else (0, 255, 0), 2)
            cv2.imshow("JEPA phone stream", img)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                return True

        if save and meta.get("recording"):
            if sess_dir is None:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                sess_dir = os.path.join("data", "raw", "pc_" + ts)
                os.makedirs(os.path.join(sess_dir, "frames"), exist_ok=True)
                actions = open(os.path.join(sess_dir, "actions.csv"), "w")
                actions.write("frame_idx,t_ms,steering,throttle,seq,esp_ms,mode\n")
                print("[pc_stream] lưu copy →", sess_dir)
            n += 1
            with open(os.path.join(sess_dir, "frames", "%06d.jpg" % n), "wb") as f:
                f.write(jpg)
            actions.write("%d,%d,%.4f,%.4f,%s,%s,%s\n" % (
                n, meta.get("t_ms", 0), meta.get("steering", 0.0), meta.get("throttle", 0.0),
                meta.get("seq", -1), meta.get("esp_ms", -1), meta.get("mode", -1)))
        elif save and sess_dir and not meta.get("recording"):
            actions.close()
            print("[pc_stream] đóng session %s (%d frame)" % (sess_dir, n))
            sess_dir, actions, n = None, None, 0
    if actions:
        actions.close()
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--save", action="store_true",
                    help="lưu copy vào data/raw/pc_<ts> khi app đang REC")
    a = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", a.port))
    srv.listen(1)
    print("[pc_stream] nghe 0.0.0.0:%d — đặt PC_HOST trong app = IP máy này. Chờ phone…" % a.port)
    print("[pc_stream] LƯU Ý: app phải đang MỞ (foreground, camera chạy) thì mới có frame.")
    try:
        while True:
            conn, addr = srv.accept()
            print("[pc_stream] phone %s đã nối — chờ frame (nếu im = app không ở foreground)…" % (addr,))
            try:
                if handle_conn(conn, a.save):
                    break
            except Exception as e:
                print("[pc_stream] lỗi:", e)
            finally:
                conn.close()
                print("[pc_stream] mất kết nối, chờ lại…")
    except KeyboardInterrupt:
        print("\n[pc_stream] thoát.")
    finally:
        srv.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
