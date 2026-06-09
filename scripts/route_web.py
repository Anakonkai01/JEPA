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


def _atomic_write(path: Path, payload: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(path)


@app.get("/")
def index():
    return send_file(HTML_PATH)


@app.get("/api/graph")
def api_graph():
    xy = np.round(G.XY.astype(np.float64), 2)
    return jsonify({
        "n": len(G.Zn),
        "xy": xy.tolist(),
        "suid": np.asarray(G.suid).astype(int).tolist(),
        "extent": [float(xy[:, 0].min()), float(xy[:, 0].max()),
                   float(xy[:, 1].min()), float(xy[:, 1].max())],
    })


@app.get("/api/node_image/<int:node>")
def api_node_image(node: int):
    if not (0 <= node < len(G.Zn)):
        return jsonify({"error": "node out of range"}), 404
    p = G.frame_path(node)
    if not p.is_absolute():
        p = ROOT / p          # graph lưu path tương đối repo root; Flask resolve theo scripts/
    if not p.exists():
        return jsonify({"error": f"frame missing: {p}"}), 404
    return send_file(p, mimetype="image/jpeg", max_age=86400)


@app.get("/api/suggest")
def api_suggest():
    """?wps=12,805,99&spacing=4[&from=live] -> Dijkstra nối tuần tự các waypoint."""
    try:
        wps = [int(v) for v in request.args.get("wps", "").split(",") if v.strip()]
    except ValueError:
        return jsonify({"error": "wps phải là id node"}), 400
    spacing = float(request.args.get("spacing", 4.0))
    if request.args.get("from") == "live":      # nối từ vị trí xe hiện tại (nếu đang live)
        st = _read_live()
        if st and st.get("cur") is not None:
            wps = [int(st["cur"])] + wps
    if len(wps) < 2:
        return jsonify({"path": wps, "subgoals": wps, "legs": [], "length_m": 0.0})
    full, subs, legs, total = [], [], [], 0.0
    for a, b in zip(wps[:-1], wps[1:]):
        leg = G.plan_route(int(a), int(b))
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
        wps = [int(v) for v in body["waypoints"]]
        mode = body.get("mode", "graph")
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"route không hợp lệ: {e}"}), 400
    if mode not in ("graph", "direct"):
        return jsonify({"error": "mode phải là graph|direct"}), 400
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
    p = ROUTES_DIR / f"{_safe_name(name)}.json"
    if p.exists():
        p.unlink()
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
        "waypoints": r["waypoints"], "spacing": r.get("spacing", 4.0), "ts": time.time(),
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
    ap.add_argument("--port", type=int, default=5060)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    G = TopoGraph.load(args.graph)
    print(f"[web] graph {args.graph}: {len(G.Zn)} nodes | routes -> {ROUTES_DIR}")
    print(f"[web] mở http://<PC>:{args.port} (cùng mạng/Tailscale)")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
