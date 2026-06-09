#!/usr/bin/env python3
"""Render the TopoGraph as a map so you can PICK a goal node id (no goal photo needed).

Nodes are plotted at their GPS position (metres, north-up), coloured by domain, with sparse node-id
labels. Read a node id near where you want the car to go, then:

    PYTHONPATH=src python scripts/inference_loop.py --goal-node <id>

Optional ``--mark-current`` grabs one frame from the phone stream, localises it, and marks the
car's CURRENT node (red ★) + prints its id — so you pick a goal that's actually elsewhere.

    PYTHONPATH=src python scripts/pick_goal.py --out data/graph/goal_map.png
    PYTHONPATH=src python scripts/pick_goal.py --mark-current --highlight 9960
"""
from __future__ import annotations

import argparse

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from jepa_wm.nav.graph import TopoGraph


def _capture_current_node(graph, port):
    """Grab one frame from the phone, encode nav latent, localize -> current node id."""
    import socket, struct, torch, cv2
    from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder
    from PIL import Image

    def recvall(s, n):
        b = bytearray()
        while len(b) < n:
            c = s.recv(n - len(b))
            if not c:
                return None
            b += c
        return bytes(b)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port)); srv.listen(1)
    print(f"[pick] --mark-current: chờ phone (port {port})… để app stream về.")
    conn, _ = srv.accept()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    enc = load_encoder(dev)
    rgb = gps = None
    for _ in range(15):                                    # bỏ vài frame cho cam ổn định
        hdr = recvall(conn, 4)
        if not hdr:
            break
        meta = __import__("json").loads(recvall(conn, struct.unpack(">I", hdr)[0]).decode())
        jpg = recvall(conn, struct.unpack(">I", recvall(conn, 4))[0])
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            rgb = img[:, :, ::-1].copy()
            if meta.get("lat", 0) and meta.get("lon", 0):
                gps = (float(meta["lat"]), float(meta["lon"]))
    conn.close(); srv.close()
    if rgb is None:
        return None
    x = Image.fromarray(rgb).resize((384, 384), Image.BILINEAR)
    t = torch.from_numpy(np.asarray(x, np.float32)).permute(2, 0, 1) / 255.0
    t = ((t - IMAGENET_MEAN) / IMAGENET_STD).unsqueeze(0).unsqueeze(2).to(dev)
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=dev == "cuda"):
        nav = enc(t).float().mean(1)[0].cpu().numpy()
    return graph.localize(nav, gps_prior=gps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="data/graph/topograph.pt")
    ap.add_argument("--out", default="data/graph/goal_map.png")
    ap.add_argument("--label-stride", type=int, default=150, help="nhãn id mỗi N node")
    ap.add_argument("--highlight", type=int, default=None, help="đánh dấu 1 node (xác nhận lựa chọn)")
    ap.add_argument("--mark-current", action="store_true", help="chụp 1 frame phone → localize → đánh dấu chỗ xe")
    ap.add_argument("--port", type=int, default=5055)
    args = ap.parse_args()

    graph = TopoGraph.load(args.graph)
    XY = graph.XY
    print(f"[pick] {len(XY)} node | extent x[{XY[:,0].min():.0f},{XY[:,0].max():.0f}] "
          f"y[{XY[:,1].min():.0f},{XY[:,1].max():.0f}] m")

    cur = _capture_current_node(graph, args.port) if args.mark_current else None
    if cur is not None:
        print(f"[pick] xe ĐANG ở node {cur} (GPS xy {XY[cur].round(1)}) — chọn goal Ở CHỖ KHÁC.")

    plt.figure(figsize=(13, 13))
    domains = np.array([graph.roots[int(r)].domain for r in graph.node_root])
    for dom in np.unique(domains):
        m = domains == dom
        plt.scatter(XY[m, 0], XY[m, 1], s=6, alpha=0.5, label=dom)
    for i in range(0, len(XY), args.label_stride):
        plt.annotate(str(i), (XY[i, 0], XY[i, 1]), fontsize=6, alpha=0.7)
    if args.highlight is not None and 0 <= args.highlight < len(XY):
        plt.scatter(*XY[args.highlight], s=200, marker="*", c="lime", edgecolors="k",
                    zorder=5, label=f"goal {args.highlight}")
    if cur is not None:
        plt.scatter(*XY[cur], s=220, marker="X", c="red", edgecolors="k", zorder=6, label=f"xe @ {cur}")
    plt.gca().set_aspect("equal"); plt.grid(alpha=0.3)
    plt.xlabel("Đông (m)"); plt.ylabel("Bắc (m)")
    plt.title(f"TopoGraph {len(XY)} node — chọn goal-node id rồi: inference_loop.py --goal-node <id>")
    plt.legend(markerscale=2, fontsize=8)
    plt.savefig(args.out, dpi=130, bbox_inches="tight")
    print(f"[pick] ✓ map: {args.out} — mở ảnh, đọc id node gần ĐÍCH, chạy: "
          f"PYTHONPATH=src python scripts/inference_loop.py --goal-node <id>")


if __name__ == "__main__":
    main()
