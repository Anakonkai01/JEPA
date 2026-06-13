#!/usr/bin/env python3
"""Web route planner — chọn goal/subgoal cho xe trên map 2D + ảnh, lưu route, chạy live.

Server Flask đọc TopoGraph (data/graph/topograph.pt) và phục vụ:
  * map 2D toàn bộ node + đường session (client canvas, pan/zoom);
  * ảnh frame của từng node (kết hợp ẢNH + 2D khi pick waypoint);
  * GỢI Ý: Dijkstra nối các waypoint đã chọn (vẽ đường + subgoal ~spacing m);
  * lưu/đọc route -> data/routes/<name>.json  (mode per-route: "graph" | "direct");
  * kích hoạt route / STOP -> data/routes/active.json (inference_loop --web watch file này);
  * trạng thái live: đọc data/routes/live_status.json + live_frame.jpg do inference_loop ghi.

Chạy (không cần GPU, không cần xe — phần live chỉ sáng khi inference_loop --web đang chạy):
    PYTHONPATH=src python scripts/route_web.py            # http://<PC>:5060
    PYTHONPATH=src python scripts/inference_loop.py --web # xe theo route từ web
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request, send_file

from jepa_wm.nav.graph import TopoGraph

ROOT = Path(__file__).resolve().parents[1]
ROUTES_DIR = ROOT / "data" / "routes"
HTML_PATH = ROOT / "web" / "route_planner.html"

app = Flask(__name__)
G: TopoGraph | None = None


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", name.strip())[:64]
    if not name:
        raise ValueError("empty route name")
    return name


def _atomic_write(path: Path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(path)


@app.get("/")
def index():
    return send_file(HTML_PATH)


@app.get("/api/graph")
def api_graph():
    if G is None:                      # manual-only mode (không có graph — vd indoor)
        return jsonify({"n": 0, "xy": [], "suid": [], "heading": [], "extent": [0, 1, 0, 1]})
    xy = np.round(G.XY.astype(np.float64), 2)
    return jsonify({
        "n": len(G.Zn),
        "xy": xy.tolist(),
        "suid": np.asarray(G.suid).astype(int).tolist(),
        "heading": np.round(G.heading.astype(np.float64), 3).tolist(),
        "extent": [float(xy[:, 0].min()), float(xy[:, 0].max()),
                   float(xy[:, 1].min()), float(xy[:, 1].max())],
    })


@app.get("/api/node_image/<int:node>")
def api_node_image(node: int):
    if G is None or not (0 <= node < len(G.Zn)):
        return jsonify({"error": "node out of range"}), 404
    p = G.frame_path(node)
    if not p.is_absolute():
        p = ROOT / p          # graph lưu path tương đối repo root; Flask resolve theo scripts/
    if not p.exists():
        return jsonify({"error": f"frame missing: {p}"}), 404
    return send_file(p, mimetype="image/jpeg", max_age=86400)


@app.get("/api/suggest")
def api_suggest():
    """?wps=12,805,99&spacing=4[&from=live][&turn=3&switch=1] -> Dijkstra nối
    tuần tự các waypoint (turn/switch = penalty m/rad đổi-hướng & m/lần đổi-session)."""
    if G is None:
        return jsonify({"error": "không có graph"}), 400
    try:
        wps = [int(v) for v in request.args.get("wps", "").split(",") if v.strip()]
    except ValueError:
        return jsonify({"error": "wps phải là id node"}), 400
    spacing = float(request.args.get("spacing", 4.0))
    plan_kw = {}
    if "turn" in request.args:
        plan_kw["turn_penalty_m"] = float(request.args["turn"])
    if "switch" in request.args:
        plan_kw["switch_penalty_m"] = float(request.args["switch"])
    if request.args.get("from") == "live":      # nối từ vị trí xe hiện tại (nếu đang live)
        st = _read_live()
        if st and st.get("cur") is not None:
            wps = [int(st["cur"])] + wps
    if len(wps) < 2:
        return jsonify({"path": wps, "subgoals": wps, "legs": [], "length_m": 0.0})
    full, subs, legs, total = [], [], [], 0.0
    for a, b in zip(wps[:-1], wps[1:]):
        leg = G.plan_route(int(a), int(b), **plan_kw)
        if leg is None:
            return jsonify({"error": f"không có đường {a} -> {b} trên graph"}), 422
        seg = leg if not full else leg[1:]
        full.extend(seg)
        d = sum(float(np.linalg.norm(G.XY[v] - G.XY[u])) for u, v in zip(leg[:-1], leg[1:]))
        legs.append({"from": a, "to": b, "nodes": len(leg), "length_m": round(d, 1)})
        total += d
        sg = G.extract_subgoals(leg, spacing_m=spacing)
        subs.extend(sg if not subs else sg[1:])
    return jsonify({"path": full, "subgoals": subs, "legs": legs, "length_m": round(total, 1)})


# ---------------- route TAY (teach & repeat): chụp subgoal từ live_frame ----------------
def _manual_dir(name: str) -> Path:
    return ROUTES_DIR / "manual" / name


def _manual_meta(name: str) -> list[dict]:
    p = _manual_dir(name) / "meta.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


@app.post("/api/manual/snap")
def api_manual_snap():
    """Chụp live_frame.jpg hiện tại làm subgoal kế của route tay <name> (kèm xy nếu xe có GPS).
    Lái xe bằng remote tới chỗ muốn làm subgoal rồi bấm — teach & repeat kiểu ViNG."""
    body = request.get_json(force=True)
    name = _safe_name(body["name"])
    frame = ROUTES_DIR / "live_frame.jpg"
    if not frame.exists() or time.time() - frame.stat().st_mtime > 3.0:
        return jsonify({"error": "không có frame mới — phone/inference_loop --web chưa stream"}), 409
    meta = _manual_meta(name)
    d = _manual_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    i = len(meta)
    img = d / f"{i:03d}.jpg"
    img.write_bytes(frame.read_bytes())
    st = _read_live()
    xy = st.get("xy") if st and time.time() - st.get("ts", 0) < 3.0 else None
    meta.append({"img": f"manual/{name}/{img.name}", "xy": xy})
    _atomic_write(d / "meta.json", meta)          # type: ignore[arg-type]
    return jsonify({"ok": True, "i": i, "img": meta[-1]["img"], "xy": xy, "n": len(meta)})


@app.post("/api/manual/undo")
def api_manual_undo():
    body = request.get_json(force=True)
    name = _safe_name(body["name"])
    meta = _manual_meta(name)
    if not meta:
        return jsonify({"error": "route tay rỗng"}), 404
    last = meta.pop()
    try:
        (ROUTES_DIR / last["img"]).unlink(missing_ok=True)
    except OSError:
        pass
    _atomic_write(_manual_dir(name) / "meta.json", meta)  # type: ignore[arg-type]
    return jsonify({"ok": True, "n": len(meta)})


@app.get("/api/manual/<name>")
def api_manual_get(name: str):
    return jsonify(_manual_meta(_safe_name(name)))


@app.get("/api/manual_image/<name>/<int:i>")
def api_manual_image(name: str, i: int):
    p = _manual_dir(_safe_name(name)) / f"{i:03d}.jpg"
    if not p.exists():
        return jsonify({"error": "missing"}), 404
    return send_file(p, mimetype="image/jpeg", max_age=0)


@app.get("/api/routes")
def api_routes_list():
    out = []
    for p in sorted(ROUTES_DIR.glob("*.json")):
        if p.name in ("active.json", "live_status.json"):
            continue
        try:
            r = json.loads(p.read_text())
            r["name"] = p.stem
            out.append(r)
        except Exception:
            continue
    return jsonify(out)


@app.post("/api/routes")
def api_routes_save():
    body = request.get_json(force=True)
    try:
        name = _safe_name(body["name"])
        mode = body.get("mode", "graph")
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"route không hợp lệ: {e}"}), 400
    if mode == "manual":                          # route tay: subgoal = ảnh đã chụp (meta.json)
        subs = _manual_meta(name)
        if not subs:
            return jsonify({"error": "chưa chụp subgoal nào (📸 trước rồi mới lưu)"}), 400
        _atomic_write(ROUTES_DIR / f"{name}.json", {
            "mode": "manual", "subgoals": subs, "waypoints": [],
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        return jsonify({"ok": True, "name": name, "n": len(subs)})
    if mode not in ("graph", "direct"):
        return jsonify({"error": "mode phải là graph|direct|manual"}), 400
    if G is None:
        return jsonify({"error": "không có graph — chỉ dùng được route tay (manual)"}), 400
    try:
        wps = [int(v) for v in body["waypoints"]]
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"route không hợp lệ: {e}"}), 400
    if not wps:
        return jsonify({"error": "route rỗng"}), 400
    bad = [w for w in wps if not (0 <= w < len(G.Zn))]
    if bad:
        return jsonify({"error": f"node ngoài graph: {bad}"}), 400
    _atomic_write(ROUTES_DIR / f"{name}.json", {
        "mode": mode, "waypoints": wps,
        "spacing": float(body.get("spacing", 4.0)),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return jsonify({"ok": True, "name": name})


@app.delete("/api/routes/<name>")
def api_routes_delete(name: str):
    nm = _safe_name(name)
    p = ROUTES_DIR / f"{nm}.json"
    mdir = _manual_dir(nm)                         # dọn LUÔN ảnh+meta route tay → teach lại cùng tên = SẠCH
    existed = p.exists() or mdir.exists()          # (snap nối thêm vào meta cũ → xoá json thôi vẫn cộng dồn)
    if p.exists():
        p.unlink()
    if mdir.exists():
        shutil.rmtree(mdir, ignore_errors=True)
    if existed:
        return jsonify({"ok": True})
    return jsonify({"error": "không thấy route"}), 404


@app.post("/api/activate")
def api_activate():
    body = request.get_json(force=True)
    name = _safe_name(body["name"])
    p = ROUTES_DIR / f"{name}.json"
    if not p.exists():
        return jsonify({"error": "không thấy route"}), 404
    r = json.loads(p.read_text())
    _atomic_write(ROUTES_DIR / "active.json", {
        "cmd": "run", "name": name, "mode": r.get("mode", "graph"),
        "waypoints": r.get("waypoints", []), "subgoals": r.get("subgoals", []),
        "spacing": r.get("spacing", 4.0), "ts": time.time(),
    })
    return jsonify({"ok": True, "name": name})


@app.post("/api/stop")
def api_stop():
    _atomic_write(ROUTES_DIR / "active.json", {"cmd": "stop", "ts": time.time()})
    return jsonify({"ok": True})


def _read_live():
    p = ROUTES_DIR / "live_status.json"
    if not p.exists():
        return None
    try:
        st = json.loads(p.read_text())
    except Exception:
        return None
    return st


@app.get("/api/live")
def api_live():
    st = _read_live()
    if st is None or time.time() - st.get("ts", 0) > 5.0:
        return jsonify({"online": False})
    st["online"] = True
    return jsonify(st)


@app.get("/api/live_frame")
def api_live_frame():
    p = ROUTES_DIR / "live_frame.jpg"
    if not p.exists():
        return jsonify({"error": "no frame"}), 404
    return send_file(p, mimetype="image/jpeg", max_age=0)


def main():
    global G
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="data/graph/topograph.pt")
    # ⚠️ đừng dùng 5060 (port SIP — Firefox/Chrome chặn "This address is restricted")
    ap.add_argument("--port", type=int, default=8060)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    if args.graph and args.graph != "none" and Path(args.graph).exists():
        G = TopoGraph.load(args.graph)
        print(f"[web] graph {args.graph}: {len(G.Zn)} nodes | routes -> {ROUTES_DIR}")
    else:
        print(f"[web] KHÔNG có graph ({args.graph}) → manual-only mode (route tay / indoor); "
              f"routes -> {ROUTES_DIR}")
    print(f"[web] mở http://<PC>:{args.port} (cùng mạng/Tailscale)")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
