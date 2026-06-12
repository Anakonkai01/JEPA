#!/usr/bin/env python3
"""route_from_session.py — dựng route TAY (teach & repeat) OFFLINE từ một session đã REC.

Trả lời ý user 06-12: "quay bằng tính năng record như lúc thu data, đem về PC, chọn subgoal
từ đó" — ĐƯỢC, và còn lợi hơn teach live: không cần PC/route_web ngoài bãi (chỉ cần CH10 REC),
frame 10Hz + GPS đầy đủ nên chọn spacing tuỳ ý sau, cua tự DÀY theo heading. Nhược điểm DUY
NHẤT (đo 06-12, probe_route_sim): ánh sáng lúc QUAY phải ≈ lúc CHẠY — khác giờ/khác nắng là
ccos sập (30/31 subgoal không qua nổi pop-confirm 0.5 với frame khác-ngày). → quay xong chạy
ngay trong buổi đó thì OK; để hôm sau = phải quay lại.

Cách dùng:
  1. Ngoài bãi: lái 1 vòng route với CH10 REC (như thu data bình thường).
  2. Lấy session về PC (auto-upload Tailscale / adb / Drive) + `python scripts/sync_dataset.py`
     (cần actions_synced.csv; gps.csv có sẵn trong session).
  3. PYTHONPATH=src python scripts/route_from_session.py data/raw_towerpro/session_XXX ten_route \
       --step-m 0.4
  4. Route hiện trên web → đưa xe về frame 000 đúng hướng → ▶ Run.

Subgoal đặt theo quãng đường along-track (--step-m), tự DÀY ở cua (--turn-deg/--turn-step-m,
heading đo trên baseline ±0.75m cho đỡ nhiễu GPS), bỏ đoạn lùi + GPS kém (acc > --max-acc).
xy ghi theo CÙNG hệ toạ độ graph (origin topograph.pt) → pop GPS/lookahead/geo-confirm chạy y
như route teach live.
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", help="thư mục session (có frames/ gps.csv actions_synced.csv)")
    ap.add_argument("name", help="tên route tay")
    ap.add_argument("--step-m", type=float, default=0.4, help="khoảng cách subgoal đoạn thẳng")
    ap.add_argument("--turn-deg", type=float, default=15.0,
                    help="heading xoay quá ngần này so với subgoal trước → coi là CUA")
    ap.add_argument("--turn-step-m", type=float, default=0.25, help="spacing trong cua (dày hơn)")
    ap.add_argument("--start-s", type=float, default=0.0, help="bỏ ngần này giây đầu session")
    ap.add_argument("--end-s", type=float, default=0.0, help="bỏ ngần này giây cuối session (0=hết)")
    ap.add_argument("--max-acc", type=float, default=15.0, help="bỏ frame GPS accuracy > (m)")
    ap.add_argument("--routes-dir", default="data/routes")
    ap.add_argument("--graph", default="data/graph/topograph.pt",
                    help="lấy origin lat/lon (xy phải CÙNG hệ với graph để pop GPS chạy đúng)")
    ap.add_argument("--force", action="store_true", help="ghi đè route trùng tên")
    args = ap.parse_args()

    sdir = Path(args.session)
    gps_f, act_f = sdir / "gps.csv", sdir / "actions_synced.csv"
    assert gps_f.exists(), f"thiếu {gps_f}"
    assert act_f.exists(), f"thiếu {act_f} (chạy scripts/sync_dataset.py trước)"

    from jepa_wm.nav.graph import TopoGraph
    g = TopoGraph.load(args.graph)
    lat0, lon0 = g.origin
    mlon = 111320.0 * math.cos(math.radians(lat0))

    gv = np.genfromtxt(gps_f, delimiter=",", names=True)
    av = np.genfromtxt(act_f, delimiter=",", names=True)
    assert gv.size > 5 and av.size > 10, "session quá ngắn"
    gt = gv["t_ms"]
    gx = (gv["lon"] - lon0) * mlon
    gy = (gv["lat"] - lat0) * _MLAT
    gacc = gv["acc"] if "acc" in (gv.dtype.names or ()) else np.zeros_like(gt)

    ft = av["t_scene_ms"]; fidx = av["frame_idx"].astype(int)
    thr = av["throttle"]
    t0, t1 = ft[0] + args.start_s * 1000, ft[-1] - args.end_s * 1000
    fx = np.interp(ft, gt, gx); fy = np.interp(ft, gt, gy)
    facc = np.interp(ft, gt, gacc)
    # heading trên baseline ±0.75s (~±0.7m @1m/s) — GPS noise 0.44m nên baseline ngắn = nhiễu
    hx = np.interp(ft + 750, gt, gx) - np.interp(ft - 750, gt, gx)
    hy = np.interp(ft + 750, gt, gy) - np.interp(ft - 750, gt, gy)
    fhd = np.arctan2(hy, hx)

    picks: list[int] = []
    last_xy = None; last_hd = None
    for i in range(len(ft)):
        if not (t0 <= ft[i] <= t1) or facc[i] > args.max_acc:
            continue
        if thr[i] < -0.02:                      # đang lùi → camera quay lưng quỹ đạo, bỏ
            last_xy = None                       # đứt mạch: snap lại khi tiến tiếp
            continue
        if not (sdir / "frames" / f"{fidx[i]:06d}.jpg").exists():
            continue
        if last_xy is None:
            picks.append(i); last_xy = (fx[i], fy[i]); last_hd = fhd[i]
            continue
        d = math.dist((fx[i], fy[i]), last_xy)
        dh = abs((fhd[i] - last_hd + math.pi) % (2 * math.pi) - math.pi)
        step = args.turn_step_m if math.degrees(dh) >= args.turn_deg else args.step_m
        if d >= step:
            picks.append(i); last_xy = (fx[i], fy[i]); last_hd = fhd[i]

    assert len(picks) >= 2, f"chỉ chọn được {len(picks)} subgoal — session có GPS/di chuyển không?"

    out_dir = Path(args.routes_dir) / "manual" / args.name
    desc_p = Path(args.routes_dir) / f"{args.name}.json"
    if (out_dir.exists() or desc_p.exists()) and not args.force:
        raise SystemExit(f"route '{args.name}' đã tồn tại — thêm --force để ghi đè")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    subs = []
    for k, i in enumerate(picks):
        dst = out_dir / f"{k:03d}.jpg"
        shutil.copyfile(sdir / "frames" / f"{fidx[i]:06d}.jpg", dst)
        subs.append({"img": f"manual/{args.name}/{k:03d}.jpg",
                     "xy": [float(fx[i]), float(fy[i])]})
    (out_dir / "meta.json").write_text(json.dumps(subs, indent=1))
    desc_p.write_text(json.dumps({
        "mode": "manual", "subgoals": subs, "waypoints": [],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_session": sdir.name,
    }, indent=1))

    seg = [math.dist(subs[k]["xy"], subs[k + 1]["xy"]) for k in range(len(subs) - 1)]
    dense = sum(1 for s in seg if s < (args.step_m + args.turn_step_m) / 2)
    print(f"[route] '{args.name}': {len(subs)} subgoal, dài {sum(seg):.1f}m, "
          f"spacing median {np.median(seg):.2f}m ({dense} đoạn dày-cua)")
    print(f"[route] nguồn: {sdir.name} (giữ ánh sáng: CHẠY CÙNG BUỔI với lúc quay!)")
    print(f"[route] → mở web là thấy route; đưa xe về subgoal 1 ĐÚNG HƯỚNG rồi ▶ Run.")


if __name__ == "__main__":
    main()
