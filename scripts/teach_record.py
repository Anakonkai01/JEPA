#!/usr/bin/env python3
"""teach_record.py — ghi route TAY DÀY tự động từ luồng live trong lúc lái 1 vòng.

Teach & repeat "đúng nghĩa" (ý user 2026-06-12): bạn lái xe 1 vòng bằng remote
(CH9 ≠ AUTO) — script này đọc vị trí xe (`live_status.json` do `inference_loop --web`
ghi mỗi tick idle) và TỰ gọi `/api/manual/snap` của route_web mỗi khi xe đi được
~`--step-m` mét. Frame chụp lấy từ CÙNG luồng live mà inference dùng lúc chạy lại
→ khớp tiền-xử-lý hoàn hảo + cùng ánh sáng hôm nay (zero domain-shift). Heading là
heading lái-tiến thật (không phải đứng-chụp lệch) → chữa lỗi "cos âm / ghim full-trái".

Xong vòng → Ctrl+C (hoặc TaskStop) → tự lưu descriptor (`/api/routes` mode=manual)
→ route hiện trên web. Đưa xe VỀ ĐÚNG CHỖ BẮT ĐẦU (frame 000) → CH9 AUTO → ▶ Run.

Chạy SONG SONG với: route_web.py (:8060) + inference_loop.py --web (đang idle stream).
"""
import argparse
import json
import math
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _post(host: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(host + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="tên route tay (vd: park_lap1)")
    ap.add_argument("--step-m", type=float, default=1.0,
                    help="đi được ngần này mét thì chụp 1 subgoal (mặc định 1.0; cua gắt giảm còn 0.5)")
    ap.add_argument("--host", default="http://127.0.0.1:8060", help="route_web")
    ap.add_argument("--routes-dir", default="data/routes")
    ap.add_argument("--max", type=int, default=600, help="trần số subgoal (an toàn)")
    args = ap.parse_args()

    live = Path(args.routes_dir) / "live_status.json"
    last_xy = None
    n = 0
    saved = {"done": False}

    def save_descriptor() -> None:
        if saved["done"]:
            return
        saved["done"] = True
        if n == 0:
            print("\n[teach] chưa chụp subgoal nào — không lưu.", flush=True)
            return
        try:
            r = _post(args.host, "/api/routes", {"name": args.name, "mode": "manual"})
            print(f"\n[teach] 💾 ĐÃ LƯU route '{args.name}' — {r.get('n', n)} subgoal.\n"
                  f"[teach] → Đưa xe VỀ CHỖ BẮT ĐẦU (frame 000, cùng hướng) → CH9 AUTO → ▶ Run.",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"\n[teach] ⚠ lưu descriptor lỗi: {e}\n"
                  f"[teach]   (ảnh + meta.json vẫn còn ở data/routes/manual/{args.name}/ — "
                  f"vào web bấm Lưu thủ công)", flush=True)

    def on_sig(*_):
        save_descriptor()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    print(f"[teach] ghi route '{args.name}': mỗi {args.step_m:g}m chụp 1 subgoal từ luồng live.",
          flush=True)
    print("[teach] LÁI XE 1 VÒNG bằng remote (CH9 ≠ AUTO). Xong thì Stop để lưu.", flush=True)
    print("[teach] chờ vị trí xe (GPS) trong live_status…", flush=True)

    waited_warned = False
    while n < args.max:
        try:
            st = json.loads(live.read_text())
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
            continue
        fresh = time.time() - st.get("ts", 0) < 3.0
        xy = st.get("xy") if fresh else None
        if xy is None:
            if not waited_warned:
                print(f"[teach]   …chưa có xy (state={st.get('state')}). Cần: phone stream + "
                      f"xe có GPS + inference idle. Đang chờ…", flush=True)
                waited_warned = True
            time.sleep(0.3)
            continue
        moved = last_xy is None or math.dist(xy, last_xy) >= args.step_m
        if not moved:
            time.sleep(0.12)
            continue
        try:
            r = _post(args.host, "/api/manual/snap", {"name": args.name})
        except urllib.error.HTTPError:
            time.sleep(0.3)          # 409 = frame chưa mới → chờ stream cập nhật
            continue
        except Exception as e:       # noqa: BLE001
            print(f"[teach] snap lỗi: {e}", flush=True)
            time.sleep(0.3)
            continue
        if r.get("ok"):
            n = r["n"]
            snapped = r.get("xy") or xy
            seg = "" if last_xy is None else f" (+{math.dist(snapped, last_xy):.1f}m)"
            last_xy = snapped
            print(f"[teach] 📸 #{n:>3}  xy=({snapped[0]:6.1f},{snapped[1]:6.1f}){seg}", flush=True)
        time.sleep(0.12)

    print(f"[teach] đạt trần --max {args.max} subgoal — dừng + lưu.", flush=True)
    save_descriptor()


if __name__ == "__main__":
    main()
