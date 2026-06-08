#!/usr/bin/env python3
"""Kéo các session .zip mới từ Google Drive (folder JEPA) về data/raw/ bằng rclone, rồi giải nén.

Setup 1 lần: cài rclone (https://rclone.org/install/) → `rclone config` tạo remote tên `gdrive`
(loại "drive", OAuth bằng tài khoản Google của bạn). rclone (full scope) thấy được file app tạo bằng
scope drive.file.

Dùng:
  python tools/pull_drive.py                                    # remote mặc định gdrive:JEPA, dest data/raw
  python tools/pull_drive.py --remote gdrive:JEPA
  python tools/pull_drive.py --dest data/raw_towerpro           # giải nén vào folder khác
  python tools/pull_drive.py --delete-remote                    # xoá zip trên Drive sau khi kéo về OK
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # robot/tools/ -> repo root
DEFAULT_RAW = os.path.join(ROOT, "data", "raw")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="gdrive:JEPA", help="remote:folder rclone")
    ap.add_argument("--dest", default=None, help="thư mục đích (mặc định data/raw)")
    ap.add_argument("--delete-remote", action="store_true", help="xoá zip trên Drive sau khi giải nén")
    a = ap.parse_args()

    dest = os.path.abspath(a.dest) if a.dest else DEFAULT_RAW

    if shutil.which("rclone") is None:
        sys.exit("Chưa có rclone. Cài: https://rclone.org/install/  rồi `rclone config` tạo remote 'gdrive'.")
    os.makedirs(dest, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        print(f"rclone copy {a.remote} -> tmp (*.zip)…")
        if subprocess.run(["rclone", "copy", a.remote, tmp, "--include", "*.zip", "-P"]).returncode != 0:
            sys.exit("rclone copy lỗi (kiểm tra remote/đăng nhập).")
        zips = sorted(glob.glob(os.path.join(tmp, "*.zip")))
        if not zips:
            print("Không có zip nào trên Drive.")
            return
        for z in zips:
            name = os.path.splitext(os.path.basename(z))[0]
            out = os.path.join(dest, name)
            if os.path.exists(out):
                print(f"  bỏ qua (đã có) {name}")
            else:
                try:
                    with zipfile.ZipFile(z) as zf:
                        zf.extractall(out)
                    print(f"  giải nén -> {os.path.relpath(out)}/{name}")
                except Exception as e:
                    shutil.rmtree(out, ignore_errors=True)
                    print(f"  LỖI (bỏ qua) {name}: {e}")
            if a.delete_remote:
                subprocess.run(["rclone", "delete", f"{a.remote}/{os.path.basename(z)}"])
    print("Xong.")


if __name__ == "__main__":
    main()
