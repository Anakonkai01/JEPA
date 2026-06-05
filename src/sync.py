#!/usr/bin/env python3
"""Re-pair mỗi frame với action (+ IMU) bằng NỘI SUY từ telemetry/cảm biến tại đúng thời điểm cảnh.

Vì sao cần: actions.csv online chỉ ghép best-effort. Ở đây ta nội suy lại tại thời điểm CẢNH THẬT của
frame, bù độ trễ camera δ_cam:
  - Data CŨ (actions.csv KHÔNG có cột dcam_ms): t_ms = lúc callback → trừ δ_cam (mặc định 100ms) ra
    thời điểm phơi sáng.
  - Data MỚI (CÓ cột dcam_ms): app đã đặt t_ms = thời điểm phơi sáng → offset 0.

Xuất MỖI session (giữ nguyên file gốc):
  - actions_synced.csv : frame_idx, t_scene_ms, steering, throttle, mode
  - imu_synced.csv     : frame_idx, t_scene_ms, gx,gy,gz, ax,ay,az, rx,ry,rz   (nội suy IMU tại t_scene_ms)
IMU không có độ trễ như camera → lấy tại t_scene_ms (đã bù δ_cam) là khớp đúng cảnh.

Loại frame: ngoài khoảng telemetry, gap telemetry > tol, hoặc mode != 1. Bỏ session rác / không telemetry.

Dùng:
  python src/sync.py                          # mọi session trong data/raw
  python src/sync.py data/raw/session_XXXX
  python src/sync.py --dcam-ms 100 --tol-ms 60 --no-imu --keep-all-modes
"""
import argparse
import bisect
import csv
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
# Session rác (xe đứng yên / quá ngắn) — xác định khi audit, xem memory dataset-v1-onboard.
JUNK = {"session_20260605_141405", "session_20260605_142220", "session_20260605_155710"}
# Cảm biến IMU xuất ra imu_synced.csv (tên file, tên cột).
IMU_FILES = [("gyro.csv", ["gx", "gy", "gz"]),
             ("accel.csv", ["ax", "ay", "az"]),
             ("rotvec.csv", ["rx", "ry", "rz"])]


def load_telemetry(path):
    tt, steer, throt, mode = [], [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                tt.append(int(row["t_ms"]))
                steer.append(float(row["steering"]))
                throt.append(float(row["throttle"]))
                mode.append(int(float(row["mode"])))
            except (KeyError, ValueError):
                continue
    return tt, steer, throt, mode


def has_dcam(actions_path):
    with open(actions_path) as f:
        return "dcam_ms" in f.readline()


def _interp_bracket(tt, vals, i, tau):
    """Nội suy tuyến tính vals tại tau, với tt[i-1] <= tau <= tt[i] (bracket i đã biết)."""
    t0, t1 = tt[i - 1], tt[i]
    if t1 == t0:
        return vals[i]
    w = (tau - t0) / (t1 - t0)
    return vals[i - 1] + w * (vals[i] - vals[i - 1])


def load_series(path):
    """Đọc 1 CSV cảm biến (t_ms, v1, v2, ...) -> (t[], [cột1[], cột2[], ...]). Rỗng nếu thiếu file."""
    t, cols = [], None
    if not os.path.exists(path):
        return [], []
    with open(path) as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            try:
                ti = int(row[0])
                vals = [float(x) for x in row[1:]]
            except (ValueError, IndexError):
                continue
            if cols is None:
                cols = [[] for _ in vals]
            t.append(ti)
            for k, v in enumerate(vals):
                if k < len(cols):
                    cols[k].append(v)
    return t, (cols or [])


def interp_at(t, vals, tau):
    """Nội suy vals tại tau; clamp về 2 đầu nếu tau ngoài khoảng (frame mép)."""
    if not t:
        return 0.0
    if tau <= t[0]:
        return vals[0]
    if tau >= t[-1]:
        return vals[-1]
    i = bisect.bisect_left(t, tau)
    t0, t1 = t[i - 1], t[i]
    if t1 == t0:
        return vals[i]
    w = (tau - t0) / (t1 - t0)
    return vals[i - 1] + w * (vals[i] - vals[i - 1])


def write_imu(d, kept):
    """Ghi imu_synced.csv: nội suy gyro/accel/rotvec tại t_scene_ms cho từng frame đã giữ."""
    streams, header = [], ["frame_idx", "t_scene_ms"]
    for fname, names in IMU_FILES:
        t, cols = load_series(os.path.join(d, fname))
        if t and len(cols) >= len(names):
            streams.append((t, cols, names))
            header += names
    if not streams:
        return False
    with open(os.path.join(d, "imu_synced.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for idx, tau, *_ in kept:
            row = [idx, int(round(tau))]
            for t, cols, names in streams:
                for k in range(len(names)):
                    row.append(f"{interp_at(t, cols[k], tau):.5f}")
            w.writerow(row)
    return True


def sync_session(d, dcam_ms, tol_ms, keep_all_modes, do_imu):
    ap = os.path.join(d, "actions.csv")
    tp = os.path.join(d, "telemetry.csv")
    if not (os.path.exists(ap) and os.path.exists(tp)):
        return 0, 0, "thiếu csv"
    tt, steer, throt, mode = load_telemetry(tp)
    if len(tt) < 2:
        return 0, 0, "telemetry rỗng"
    offset = 0 if has_dcam(ap) else dcam_ms
    kept, dropped = [], 0
    with open(ap) as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row["frame_idx"])
                tau = int(row["t_ms"]) - offset
            except (KeyError, ValueError):
                dropped += 1
                continue
            i = bisect.bisect_left(tt, tau)
            if i == 0 or i >= len(tt):                 # ngoài khoảng telemetry
                dropped += 1
                continue
            if tt[i] - tt[i - 1] > tol_ms:             # gap telemetry quá lớn → action không tin cậy
                dropped += 1
                continue
            md = mode[i] if (tt[i] - tau) < (tau - tt[i - 1]) else mode[i - 1]   # mode = mẫu gần nhất
            if not keep_all_modes and md != 1:
                dropped += 1
                continue
            kept.append((idx, tau, _interp_bracket(tt, steer, i, tau), _interp_bracket(tt, throt, i, tau), md))
    if not kept:
        return 0, dropped, "0 frame hợp lệ"
    with open(os.path.join(d, "actions_synced.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_idx", "t_scene_ms", "steering", "throttle", "mode"])
        for idx, tau, s, th, md in kept:
            w.writerow([idx, int(round(tau)), f"{s:.4f}", f"{th:.4f}", md])
    imu_ok = write_imu(d, kept) if do_imu else False
    return len(kept), dropped, f"offset={offset:g}ms" + (" +imu" if imu_ok else "")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("session", nargs="?", help="1 session dir (mặc định: tất cả trong data/raw)")
    p.add_argument("--dcam-ms", type=float, default=100.0, help="δ_cam trừ cho data CŨ (không có cột dcam_ms)")
    p.add_argument("--tol-ms", type=float, default=60.0, help="gap telemetry tối đa quanh frame (ms)")
    p.add_argument("--keep-all-modes", action="store_true", help="không loại frame theo mode")
    p.add_argument("--no-imu", action="store_true", help="bỏ xuất imu_synced.csv")
    a = p.parse_args()

    dirs = [a.session] if a.session else sorted(glob.glob(os.path.join(RAW, "session_*")))
    tot_k = tot_d = 0
    print(f"{'session':>24} {'kept':>6} {'dropped':>8}  note")
    for d in dirs:
        name = os.path.basename(d.rstrip("/"))
        if name in JUNK:
            print(f"{name:>24} {'-':>6} {'-':>8}  (rác, bỏ)")
            continue
        k, dr, note = sync_session(d, a.dcam_ms, a.tol_ms, a.keep_all_modes, not a.no_imu)
        print(f"{name:>24} {k:>6} {dr:>8}  {note}")
        tot_k += k
        tot_d += dr
    print(f"\nTỔNG: giữ {tot_k} frame, bỏ {tot_d}.  -> actions_synced.csv + imu_synced.csv mỗi session")


if __name__ == "__main__":
    main()
