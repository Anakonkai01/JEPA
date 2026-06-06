#!/usr/bin/env python3
"""Nhận NGUYÊN session (zip) từ app điện thoại (Uploader) qua TCP → giải nén vào data/raw/<name>/.

Đây là cách lấy DATA ĐẦY ĐỦ không cần cáp: frames + actions.csv + telemetry.csv (50Hz) +
accel/gyro/rotvec/gps.csv. App tự gửi sau mỗi lần STOP (CH10 OFF). Chạy được qua Tailscale (5G).

Chạy (để nền suốt buổi):
  conda activate ai
  python tools/pc_receiver.py                # nghe 5056, lưu data/raw/
  python tools/pc_receiver.py --port 5056 --out data/raw

App điện thoại: UPLOAD_PORT khớp --port; PC_HOST = IP máy này (Tailscale 100.x hoặc LAN).
"""
import argparse
import io
import os
import socket
import struct
import zipfile


def recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        c = sock.recv(min(65536, n - len(buf)))
        if not c:
            return None
        buf.extend(c)
    return bytes(buf)


def handle(conn, outdir):
    name_len = struct.unpack(">I", recvall(conn, 4))[0]
    name = recvall(conn, name_len).decode("utf-8")
    zip_len = struct.unpack(">Q", recvall(conn, 8))[0]
    print("[recv] đang nhận %s (%.1f MB)…" % (name, zip_len / 1e6))
    data = recvall(conn, zip_len)
    if data is None or len(data) != zip_len:
        print("[recv] THIẾU data, bỏ:", name)
        return
    dest = os.path.join(outdir, name)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dest)
    n = sum(len(files) for _, _, files in os.walk(dest))
    print("[recv] ✓ %s → %s (%d files)" % (name, dest, n))
    conn.sendall(b"\x01")          # ack: phone xoá zip tạm + coi như gửi xong


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5056)
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", a.port))
    srv.listen(2)
    print("[recv] nghe 0.0.0.0:%d → lưu %s/. Chờ session từ điện thoại…" % (a.port, a.out))
    try:
        while True:
            conn, addr = srv.accept()
            print("[recv] phone %s nối" % (addr,))
            try:
                handle(conn, a.out)
            except Exception as e:
                print("[recv] lỗi:", e)
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\n[recv] thoát.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
