#!/usr/bin/env python3
"""Kéo các session .zip mới từ Google Drive (folder JEPA) về data/raw/ bằng rclone, rồi giải nén.

Setup 1 lần: cài rclone (https://rclone.org/install/) → `rclone config` tạo remote tên `gdrive`
(loại "drive", OAuth bằng tài khoản Google của bạn). rclone (full scope) thấy được file app tạo bằng
scope drive.file.

Logic (sửa 2026-06-08): LIỆT KÊ remote trước, so với **các folder đã giải nén** dưới dest →
chỉ tải về những zip còn THIẾU (folder chưa có). Trước đây nó tải HẾT zip về tmp rồi mới check
folder → re-run là tải lại toàn bộ. Giờ folder đã giải nén = skip, không tốn băng thông.

Dùng:
  python tools/pull_drive.py                                    # remote mặc định gdrive:JEPA, dest data/raw
  python tools/pull_drive.py --remote gdrive:JEPA
  python tools/pull_drive.py --dest data/raw_towerpro           # giải nén vào folder khác
  python tools/pull_drive.py --status                           # chỉ so sánh remote vs local, KHÔNG tải
  python tools/pull_drive.py --delete-remote                    # xoá zip trên Drive sau khi giải nén OK
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


def list_remote_zips(remote):
    """Trả về danh sách tên file *.zip (basename) trên remote."""
    r = subprocess.run(
        ["rclone", "lsf", remote, "--include", "*.zip"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"rclone lsf lỗi (kiểm tra remote/đăng nhập):\n{r.stderr.strip()}")
    return sorted(n.strip().rstrip("/") for n in r.stdout.splitlines() if n.strip().endswith(".zip"))


def extracted_ok(out):
    """Folder giải nén được coi là 'đã có' nếu tồn tại VÀ không rỗng."""
    return os.path.isdir(out) and any(os.scandir(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="gdrive:JEPA", help="remote:folder rclone")
    ap.add_argument("--dest", default=None, help="thư mục đích (mặc định data/raw)")
    ap.add_argument("--status", action="store_true", help="chỉ so sánh remote vs local, không tải")
    ap.add_argument("--delete-remote", action="store_true", help="xoá zip trên Drive sau khi giải nén")
    a = ap.parse_args()

    dest = os.path.abspath(a.dest) if a.dest else DEFAULT_RAW

    if shutil.which("rclone") is None:
        sys.exit("Chưa có rclone. Cài: https://rclone.org/install/  rồi `rclone config` tạo remote 'gdrive'.")
    os.makedirs(dest, exist_ok=True)

    zips = list_remote_zips(a.remote)
    if not zips:
        print(f"Không có zip nào trên {a.remote}.")
        return

    # Phân loại theo folder giải nén đã tồn tại dưới dest.
    have, missing = [], []
    for z in zips:
        name = os.path.splitext(z)[0]
        out = os.path.join(dest, name)
        (have if extracted_ok(out) else missing).append((z, name, out))

    print(f"Remote {a.remote}: {len(zips)} zip | đã giải nén ở {os.path.relpath(dest)}: "
          f"{len(have)} | thiếu: {len(missing)}")
    for z, name, _ in have:
        print(f"  ✓ {name}")
    for z, name, _ in missing:
        print(f"  ↓ {name}  (sẽ tải)")

    if a.status:
        return
    if not missing:
        print("Không có gì để tải — tất cả đã giải nén.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        for z, name, out in missing:
            print(f"rclone copy {a.remote}/{z} …")
            r = subprocess.run(["rclone", "copyto", f"{a.remote}/{z}", os.path.join(tmp, z), "-P"])
            if r.returncode != 0:
                print(f"  LỖI tải {z} (bỏ qua).")
                continue
            try:
                with zipfile.ZipFile(os.path.join(tmp, z)) as zf:
                    zf.extractall(out)
                print(f"  giải nén -> {os.path.relpath(out)}/")
            except Exception as e:
                shutil.rmtree(out, ignore_errors=True)
                print(f"  LỖI giải nén (bỏ qua) {name}: {e}")
                continue
            if a.delete_remote:
                subprocess.run(["rclone", "delete", f"{a.remote}/{z}"])
            os.remove(os.path.join(tmp, z))
    print("Xong.")


if __name__ == "__main__":
    main()
