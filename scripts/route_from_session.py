#!/usr/bin/env python3
"""route_from_session.py — dựng route TAY (teach & repeat) OFFLINE từ một session đã REC.

Trả lời ý user 06-12: "quay bằng tính năng record như lúc thu data, đem về PC, chọn subgoal
từ đó" — ĐƯỢC, và còn lợi hơn teach live: không cần PC/route_web ngoài bãi (chỉ cần CH10 REC),
frame 10Hz + GPS đầy đủ nên chọn spacing tuỳ ý sau, cua tự DÀY theo heading.

LƯU Ý ÁNH SÁNG (đính chính 06-14): CEM quyết-định lái bằng **patchL1 trên patch tokens** (đo
06-13: lighting MINH OAN cho quyết-định — lật argmin 2-3%), chỉ **cosine/localize** mới nhạy sáng
(dùng cho cổng pop). Nên route khác-buổi vẫn lái được nếu pop dựa GPS (POP=0). Kiểm thật bằng
`scripts/probe_l1_lighting.py` (cross-session patchL1) thay vì giả định.

Lõi tách hàm (load_session_track / pick_subgoals / build_route_from_session) để web (route_web.py)
và CLI dùng CHUNG.

Cách dùng (CLI):
  PYTHONPATH=src python scripts/route_from_session.py data/raw_towerpro/session_XXX ten_route --step-m 0.4
Hoặc dựng trên web: bash run_web.sh → card "Route từ Session".
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np

_MLAT = 110574.0


def graph_origin(graph_path="data/graph/topograph.pt"):
    """(lat0, lon0) của graph — xy route PHẢI cùng hệ để pop GPS/lookahead chạy đúng."""
    from jepa_wm.nav.graph import TopoGraph
    return TopoGraph.load(graph_path).origin


def load_session_track(sdir: Path, lat0: float, lon0: float) -> dict:
    """Per-frame track trong hệ toạ-độ graph: ft, fidx, fx, fy, fhd, facc, thr (numpy arrays)."""
    sdir = Path(sdir)
    gps_f, act_f = sdir / "gps.csv", sdir / "actions_synced.csv"
    if not gps_f.exists():
        raise FileNotFoundError(f"thiếu {gps_f}")
    if not act_f.exists():
        raise FileNotFoundError(f"thiếu {act_f} (chạy scripts/sync_dataset.py trước)")
    mlon = 111320.0 * math.cos(math.radians(lat0))
    gv = np.genfromtxt(gps_f, delimiter=",", names=True)
    av = np.genfromtxt(act_f, delimiter=",", names=True)
    if gv.size <= 5 or av.size <= 10:
        raise ValueError("session quá ngắn")
    gt = gv["t_ms"]
    gx = (gv["lon"] - lon0) * mlon
    gy = (gv["lat"] - lat0) * _MLAT
    gacc = gv["acc"] if "acc" in (gv.dtype.names or ()) else np.zeros_like(gt)
    ft = av["t_scene_ms"]; fidx = av["frame_idx"].astype(int)
    thr = av["throttle"]
    fx = np.interp(ft, gt, gx); fy = np.interp(ft, gt, gy)
    facc = np.interp(ft, gt, gacc)
    hx = np.interp(ft + 750, gt, gx) - np.interp(ft - 750, gt, gx)
    hy = np.interp(ft + 750, gt, gy) - np.interp(ft - 750, gt, gy)
    fhd = np.arctan2(hy, hx)
    return {"ft": ft, "fidx": fidx, "fx": fx, "fy": fy, "fhd": fhd, "facc": facc, "thr": thr}


def pick_subgoals(track: dict, sdir: Path, *, step_m=0.4, turn_deg=15.0, turn_step_m=0.25,
                  start_s=0.0, end_s=0.0, max_acc=15.0) -> list[int]:
    """Chọn index subgoal theo quãng-đường along-track, DÀY ở cua, bỏ lùi + GPS kém + frame thiếu."""
    sdir = Path(sdir)
    ft, fidx = track["ft"], track["fidx"]
    fx, fy, fhd, facc, thr = track["fx"], track["fy"], track["fhd"], track["facc"], track["thr"]
    t0, t1 = ft[0] + start_s * 1000, ft[-1] - end_s * 1000
    picks: list[int] = []
    last_xy = None; last_hd = None
    for i in range(len(ft)):
        if not (t0 <= ft[i] <= t1) or facc[i] > max_acc:
            continue
        if thr[i] < -0.02:                       # đang lùi → bỏ
            last_xy = None
            continue
        if not (sdir / "frames" / f"{fidx[i]:06d}.jpg").exists():
            continue
        if last_xy is None:
            picks.append(i); last_xy = (fx[i], fy[i]); last_hd = fhd[i]
            continue
        d = math.dist((fx[i], fy[i]), last_xy)
        dh = abs((fhd[i] - last_hd + math.pi) % (2 * math.pi) - math.pi)
        step = turn_step_m if math.degrees(dh) >= turn_deg else step_m
        if d >= step:
            picks.append(i); last_xy = (fx[i], fy[i]); last_hd = fhd[i]
    return picks


def build_route_from_session(sdir, name, lat0, lon0, *, routes_dir="data/routes", force=False,
                             step_m=0.4, turn_deg=15.0, turn_step_m=0.25,
                             start_s=0.0, end_s=0.0, max_acc=15.0) -> dict:
    """Dựng + ghi route từ session. Trả dict tóm tắt (n, length_m, spacing, ...)."""
    sdir = Path(sdir)
    track = load_session_track(sdir, lat0, lon0)
    picks = pick_subgoals(track, sdir, step_m=step_m, turn_deg=turn_deg, turn_step_m=turn_step_m,
                          start_s=start_s, end_s=end_s, max_acc=max_acc)
    if len(picks) < 2:
        raise ValueError(f"chỉ chọn được {len(picks)} subgoal — session có GPS/di chuyển không?")
    fidx, fx, fy = track["fidx"], track["fx"], track["fy"]
    routes_dir = Path(routes_dir)
    out_dir = routes_dir / "manual" / name
    desc_p = routes_dir / f"{name}.json"
    if (out_dir.exists() or desc_p.exists()) and not force:
        raise FileExistsError(f"route '{name}' đã tồn tại")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    subs = []
    for k, i in enumerate(picks):
        shutil.copyfile(sdir / "frames" / f"{fidx[i]:06d}.jpg", out_dir / f"{k:03d}.jpg")
        subs.append({"img": f"manual/{name}/{k:03d}.jpg", "xy": [float(fx[i]), float(fy[i])]})
    (out_dir / "meta.json").write_text(json.dumps(subs, indent=1))
    desc_p.write_text(json.dumps({
        "mode": "manual", "subgoals": subs, "waypoints": [],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "source_session": sdir.name,
    }, indent=1))
    seg = [math.dist(subs[k]["xy"], subs[k + 1]["xy"]) for k in range(len(subs) - 1)]
    dense = sum(1 for s in seg if s < (step_m + turn_step_m) / 2)
    return {"name": name, "n": len(subs), "length_m": round(sum(seg), 1),
            "spacing_med": round(float(np.median(seg)), 2), "dense_turn": dense,
            "source_session": sdir.name}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", help="thư mục session (có frames/ gps.csv actions_synced.csv)")
    ap.add_argument("name", help="tên route tay")
    ap.add_argument("--step-m", type=float, default=0.4, help="khoảng cách subgoal đoạn thẳng")
    ap.add_argument("--turn-deg", type=float, default=15.0, help="heading xoay quá ngần này → CUA")
    ap.add_argument("--turn-step-m", type=float, default=0.25, help="spacing trong cua (dày hơn)")
    ap.add_argument("--start-s", type=float, default=0.0, help="bỏ ngần này giây đầu session")
    ap.add_argument("--end-s", type=float, default=0.0, help="bỏ ngần này giây cuối session (0=hết)")
    ap.add_argument("--max-acc", type=float, default=15.0, help="bỏ frame GPS accuracy > (m)")
    ap.add_argument("--routes-dir", default="data/routes")
    ap.add_argument("--graph", default="data/graph/topograph.pt", help="lấy origin lat/lon")
    ap.add_argument("--force", action="store_true", help="ghi đè route trùng tên")
    args = ap.parse_args()

    lat0, lon0 = graph_origin(args.graph)
    try:
        r = build_route_from_session(
            args.session, args.name, lat0, lon0, routes_dir=args.routes_dir, force=args.force,
            step_m=args.step_m, turn_deg=args.turn_deg, turn_step_m=args.turn_step_m,
            start_s=args.start_s, end_s=args.end_s, max_acc=args.max_acc)
    except FileExistsError as e:
        raise SystemExit(f"{e} — thêm --force để ghi đè")
    print(f"[route] '{r['name']}': {r['n']} subgoal, dài {r['length_m']}m, "
          f"spacing median {r['spacing_med']}m ({r['dense_turn']} đoạn dày-cua)")
    print(f"[route] nguồn: {r['source_session']} — pop GPS (POP=0) thì khác-buổi vẫn chạy (CEM=L1).")
    print(f"[route] → mở web là thấy route; đưa xe về subgoal 1 ĐÚNG HƯỚNG rồi ▶ Run.")


if __name__ == "__main__":
    main()
