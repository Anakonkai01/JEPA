#!/usr/bin/env python3
"""Closed-loop autonomous driving (Phase 4) — visual subgoal navigation + V-JEPA-2-AC control.

Pipeline (ViNG-style two layers, see docs/HANDOFF.md 2026-06-08):

    phone (onboard cam) --TCP--> PC
        frame -> V-JEPA 2.1 encode {nav: 384px pooled latent, control: 256px patch tokens}
        NAV  : TopoGraph.localize(nav_latent, gps) -> plan_route(cur -> goal) -> extract_subgoals
        CTRL : CEMPlannerAC(patch tokens, state, goal=subgoal patch tokens) -> [steer, throttle]
    PC --action--> phone --USB--> ESP32   (phone relay; firmware applies it only in CH9=AUTO)

Transport (chosen 2026-06-09): the action rides BACK DOWN the same phone TCP socket the frames
came up on (``controller.PhoneRelaySender``); the Android app's PcLink downlink relays the 2
control bytes to the ESP32 over USB. Use ``--dongle`` to instead drive an ESP-NOW dongle on the PC.

State (the world model needs [speed, gx..gz, ax..az, rx..rz] per frame) comes from the phone's
stream meta (the app now serialises IMU + GPS into each frame's meta JSON). Old app builds that
lack those keys -> state falls back to zeros (control degrades but the loop still runs).

⚠️ Untested end-to-end without the car + phone + firmware AUTO mode. The wiring + units are the
faithful counterparts of the offline eval (scripts/eval_goal_reaching_ac.py), which IS verified.

    PYTHONPATH=src python scripts/inference_loop.py \
        --checkpoint checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt \
        --graph data/graph/topograph.pt --goal-image path/to/goal.jpg
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

# robot/capture for the controller transports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot" / "capture"))
import controller as ctl  # noqa: E402

from jepa_wm.data.dataset import split_sessions  # noqa: E402
from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder  # noqa: E402
from jepa_wm.models import build_model  # noqa: E402
from jepa_wm.nav.graph import TopoGraph  # noqa: E402
from jepa_wm.planning import CEMPlannerAC  # noqa: E402
from jepa_wm.planning.dynamics import CarDynamics  # noqa: E402

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


# ---------------------------------------------------------------------------
# Encoding helpers (mirror engine.encode / engine.encode_patch, but online)
# ---------------------------------------------------------------------------
def _to_tensor(rgb_u8: np.ndarray, size: int, device) -> torch.Tensor:
    """RGB uint8 HxWx3 -> normalised (1,3,1,size,size) for the V-JEPA encoder."""
    import PIL.Image as Image
    img = Image.fromarray(rgb_u8).resize((size, size), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
    x = (x - IMAGENET_MEAN) / IMAGENET_STD
    return x.unsqueeze(0).unsqueeze(2).to(device)            # (1,3,1,H,W)


class Encoders:
    """384px (native) cho CẢ nav lẫn control → 1 lần encode/frame: patch tokens (576,1024) cho control
    (per-token LN, như ACClipDataset), nav = mean-pool 576 token (khớp node graph build ở 384)."""

    def __init__(self, enc, device, size=384, fp16=False):
        self.device = device
        self.size = size
        self.fp16 = fp16 and device.startswith("cuda")    # encoder fp16 → ~nửa VRAM (cho laptop)
        self.enc = enc.half() if self.fp16 else enc

    @torch.no_grad()
    def _tokens(self, rgb_u8) -> torch.Tensor:
        x = _to_tensor(rgb_u8, self.size, self.device)
        if self.fp16:
            tok = self.enc(x.half())                      # pure fp16, không autocast
        else:
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.startswith("cuda")):
                tok = self.enc(x)
        return tok.float()[0]                             # (576, 1024)

    def both(self, rgb_u8):
        """1 forward → (nav_latent (1024,) np, ctrl_tokens (576,1024) LN'd)."""
        tok = self._tokens(rgb_u8)
        nav = tok.mean(0).cpu().numpy()                   # = build_graph node (mean-pool 384)
        return nav, F.layer_norm(tok, (tok.size(-1),))

    def nav(self, rgb_u8) -> np.ndarray:                  # one-off (goal-image localize)
        return self._tokens(rgb_u8).mean(0).cpu().numpy()

    def ctrl(self, rgb_u8) -> torch.Tensor:               # one-off (subgoal / control-only)
        tok = self._tokens(rgb_u8)
        return F.layer_norm(tok, (tok.size(-1),))         # (576, 1024)


# ---------------------------------------------------------------------------
# Phone uplink reader: keep only the LATEST frame (drop stale -> no lag buildup)
# ---------------------------------------------------------------------------
def _recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


class FrameReader(threading.Thread):
    def __init__(self, conn):
        super().__init__(daemon=True)
        self.conn = conn
        self._lock = threading.Lock()
        self._latest = None       # (meta dict, rgb_u8)
        self._seq = 0
        self.alive = True

    def run(self):
        try:
            while self.alive:
                hdr = _recvall(self.conn, 4)
                if not hdr:
                    break
                meta = json.loads(_recvall(self.conn, struct.unpack(">I", hdr)[0]).decode("utf-8"))
                jlen = struct.unpack(">I", _recvall(self.conn, 4))[0]
                jpg = _recvall(self.conn, jlen)
                if jpg is None:
                    break
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)  # BGR
                if img is None:
                    continue
                with self._lock:
                    self._latest = (meta, img[:, :, ::-1].copy())   # -> RGB
                    self._seq += 1
        except Exception:
            pass                              # phone rớt giữa chừng → kết thúc êm (main loop sẽ nối lại)
        finally:
            self.alive = False

    def latest(self):
        with self._lock:
            return (self._seq, self._latest)


class ActionHolder:
    """Resend the latest action at a fixed rate, decoupled from the (slow) compute loop.

    The firmware AUTO watchdog neutralises after CTRL_WATCHDOG_MS (500 ms) without a fresh
    command, but one encode+CEM step can exceed that — so a keep-alive thread re-sends the
    last planned action at ~12 Hz while the main loop only *updates* it when a new plan lands.
    """

    def __init__(self, sender, hz: float = 12.0):
        self.sender = sender
        self._steer = 0.0
        self._throt = 0.0
        self.alive = True
        self._lock = threading.Lock()
        self._period = 1.0 / hz
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def set(self, steer: float, throt: float):
        with self._lock:
            self._steer, self._throt = float(steer), float(throt)

    def _loop(self):
        while self.alive:
            with self._lock:
                s, t = self._steer, self._throt
            try:
                self.sender.send(s, t)
            except Exception:
                pass
            time.sleep(self._period)

    def stop(self):
        self.alive = False
        self.set(0.0, 0.0)
        try:
            self.sender.send(0.0, 0.0)        # explicit neutral on shutdown
        except Exception:
            pass


# ---------------------------------------------------------------------------
def build_state(meta: dict, columns) -> torch.Tensor:
    """Raw state vector from stream meta, in the model's column order. gz==yaw_rate; prev-action =
    telemetry steering/throttle hiện tại (= lệnh đang áp = action 'trước' cho quyết định kế)."""
    alias = {"yaw_rate": "gz", "prev_steer": "steering", "prev_throttle": "throttle"}
    vals = [float(meta.get(alias.get(c, c), 0.0) or 0.0) for c in columns]
    return torch.tensor(vals, dtype=torch.float32)


def fit_dynamics(cfg, columns, speed_idx, yaw_idx, dt):
    """Fit CarDynamics on the model's TRAIN split; fall back to unit coeffs if data missing."""
    try:
        patch_dir, raw_dir = cfg["data"]["patch_dir"], cfg["data"]["raw_dir"]
        sessions = sorted(p.stem for p in Path(patch_dir).glob("*.npy"))
        train_s, _ = split_sessions(sessions, val_frac=cfg["data"].get("val_frac", 0.2),
                                    seed=cfg.get("seed", 0))
        dyn = CarDynamics.fit(raw_dir, train_s, dt=dt, stride=cfg["data"].get("frame_stride", 2),
                              speed_idx=speed_idx, yaw_idx=yaw_idx)
        print(f"[infer] dynamics (fit): {dyn}")
        return dyn
    except Exception as e:
        print(f"[infer] dynamics fit failed ({e}); using unit coeffs")
        return CarDynamics(speed_idx=speed_idx, yaw_idx=yaw_idx, dt=dt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt")
    ap.add_argument("--graph", default="data/graph/topograph.pt")
    ap.add_argument("--goal-image", default=None, help="goal frame (full-nav: -> nearest graph node; control-only: CEM target)")
    ap.add_argument("--goal-node", type=int, default=None,
                    help="full-nav: chọn THẲNG node goal trên graph (xem scripts/pick_goal.py để lấy id) — khỏi cần ảnh")
    ap.add_argument("--goal-xy", default=None, metavar="X,Y",
                    help="full-nav: goal = node gần toạ độ (mét) này nhất — đọc X,Y trên scripts/pick_goal.py map")
    ap.add_argument("--control-only", action="store_true",
                    help="bỏ graph/nav: CEM lái thẳng để cảnh hiện tại khớp ảnh goal (chạy được trong nhà, không cần GPS; model OOD ngoài park)")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--horizon", type=int, default=4, help="CEM (MPC) lookahead steps")
    ap.add_argument("--samples", type=int, default=64, help="CEM samples (giảm = nhanh hơn)")
    ap.add_argument("--elite", type=int, default=12)
    ap.add_argument("--iters", type=int, default=2, help="CEM iterations (giảm = nhanh hơn)")
    ap.add_argument("--throttle-cap", type=float, default=0.08,
                    help="ga TỐI ĐA cho lần chạy (an toàn): box throttle = [0, cap], forward-only")
    ap.add_argument("--subgoal-spacing", type=float, default=4.0, help="metres between subgoals")
    ap.add_argument("--advance-m", type=float, default=3.0,
                    help="nhắm subgoal đầu tiên còn cách xe > ngần này (mét) → bỏ qua subgoal đã tới gần, chống kẹt")
    ap.add_argument("--steer-smooth", type=float, default=0.6,
                    help="EMA lái: steer = α·cũ + (1-α)·mới. Cao = mượt hơn (chống zigzag/văng đường). 0=tắt")
    ap.add_argument("--turn-slow", type=float, default=0.5,
                    help="cua thì giảm ga: throt *= (1 - k·|steer|). 0=tắt")
    ap.add_argument("--stale-s", type=float, default=0.4,
                    help="không có frame mới quá ngần này (giây) → NEUTRAL (link khựng, đừng giữ lệnh cũ)")
    ap.add_argument("--off-route-m", type=float, default=10.0,
                    help="node localize cách xe (GPS) xa hơn ngần này → coi như LẠC → neutral (đừng lái theo route bịa)")
    ap.add_argument("--reach-m", type=float, default=4.0,
                    help="tới đích khi GPS cách goal < ngần này (mét). Robust hơn cosine ở park tự-giống.")
    ap.add_argument("--rate", type=float, default=5.0, help="max control Hz")
    ap.add_argument("--dongle", action="store_true", help="send via ESP-NOW dongle, not phone relay")
    ap.add_argument("--dt", type=float, default=0.22)
    ap.add_argument("--fp16-encoder", action="store_true",
                    help="encoder fp16 (~nửa VRAM, hướng tới <6GB cho laptop; mặc định bf16-autocast)")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    if cv2 is None:
        ap.error("opencv-python required (pip install opencv-python)")

    # --- model + normalisation ---
    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict({k.replace("_orig_mod.", "", 1): v for k, v in ckpt["model"].items()})
    model.eval()
    state_mean = ckpt["state_mean"].to(args.device).float()
    state_std = ckpt["state_std"].to(args.device).float()
    cols = tuple(cfg["data"].get("state_columns",
                 ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    ascale = tuple(cfg["data"].get("action_scale", [1.0, 6.67]))
    speed_idx = cols.index("speed") if "speed" in cols else 0
    yaw_idx = cols.index("gz") if "gz" in cols else (cols.index("yaw_rate") if "yaw_rate" in cols else 1)
    prev_idx = (cols.index("prev_steer"), cols.index("prev_throttle")) if "prev_steer" in cols else None

    enc = load_encoder(args.device)
    encoders = Encoders(enc, args.device, fp16=args.fp16_encoder)
    dyn = fit_dynamics(cfg, cols, speed_idx, yaw_idx, args.dt)
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=args.horizon, n_samples=args.samples, n_elite=args.elite,
                           n_iter=args.iters, throttle_min=0.0,           # forward-only (no surprise reverse)
                           throttle_max=args.throttle_cap, prev_action_idx=prev_idx, device=args.device)

    # --- goal ---
    graph = goal_node = goal_nav = goal_tokens = None
    subgoal_cache: dict[int, torch.Tensor] = {}

    def subgoal_patch(node: int) -> torch.Tensor:
        if node not in subgoal_cache:
            img = cv2.imread(str(graph.frame_path(node)))
            if img is None:
                raise FileNotFoundError(f"subgoal frame missing: node {node}")
            subgoal_cache[node] = encoders.ctrl(img[:, :, ::-1].copy())
        return subgoal_cache[node]

    if args.control_only:
        if not args.goal_image:
            ap.error("--control-only cần --goal-image")
        g = cv2.imread(args.goal_image)
        if g is None:
            ap.error(f"cannot read --goal-image {args.goal_image}")
        goal_tokens = encoders.ctrl(g[:, :, ::-1].copy())      # (N,D) — fixed CEM target
        print("[infer] CONTROL-ONLY: CEM lái thẳng tới ảnh goal (bỏ graph/nav). Chạy trong nhà OK, "
              "nhưng model train ở park → OOD, action có thể không chuẩn.")
    else:
        graph = TopoGraph.load(args.graph)
        if args.goal_node is not None:                         # chọn thẳng node trên graph
            if not (0 <= args.goal_node < len(graph.Zn)):
                ap.error(f"--goal-node {args.goal_node} ngoài [0,{len(graph.Zn)})")
            goal_node = args.goal_node
        elif args.goal_xy:                                      # node gần toạ độ (mét) nhất
            try:
                gx, gy = (float(v) for v in args.goal_xy.split(","))
            except ValueError:
                ap.error('--goal-xy phải dạng "X,Y" (mét)')
            goal_node = int(np.argmin(np.linalg.norm(graph.XY - np.array([gx, gy], np.float32), axis=1)))
        elif args.goal_image:                                  # hoặc localize từ ảnh
            g = cv2.imread(args.goal_image)
            if g is None:
                ap.error(f"cannot read --goal-image {args.goal_image}")
            goal_node = graph.localize(encoders.nav(g[:, :, ::-1].copy()))
        else:
            ap.error("full-nav cần --goal-node HOẶC --goal-image")
        goal_nav = graph.Zn[goal_node]                         # L2-normalised
        print(f"[infer] GOAL = node {goal_node} "
              f"(session {graph.node_session[goal_node]} frame {graph.node_frame[goal_node]}, "
              f"GPS xy {graph.XY[goal_node].round(1)})")

    # --- TCP server: phone connects (client) ---
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"[infer] listening 0.0.0.0:{args.port} — set phone PC_HOST to this PC. "
          f"{'CONTROL-ONLY' if args.control_only else f'goal=node {goal_node}'}.")

    dongle = ctl.SerialDongleSender() if args.dongle else None
    period = 1.0 / max(args.rate, 0.1)
    try:
        while True:
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[infer] phone {addr} connected")
            sender = dongle if dongle else ctl.PhoneRelaySender(conn)
            # Phone relay: the PHONE keeps-alive (resends @12Hz over USB) so the PC sends each new
            # action ONCE — WAN (Tailscale/5G) jitter no longer trips the firmware watchdog. The
            # dongle path has no phone, so there the PC must keep-alive itself (ActionHolder).
            holder = ActionHolder(sender) if dongle else None

            def emit(s, t):
                if holder is not None:
                    holder.set(s, t)
                else:
                    sender.send(s, t)

            reader = FrameReader(conn); reader.start()
            last_seq, reached, prev_steer = -1, False, 0.0
            last_frame_t = time.time()
            try:
                while reader.alive:
                    t0 = time.time()
                    seq, item = reader.latest()
                    if item is None or seq == last_seq:
                        # SAFETY: link/stream khựng > stale_s → neutral (đừng để keep-alive giữ lệnh cũ)
                        if time.time() - last_frame_t > args.stale_s:
                            emit(0.0, 0.0); prev_steer = 0.0
                        time.sleep(0.01); continue
                    last_seq = seq; last_frame_t = time.time()
                    meta, rgb = item

                    if args.control_only:
                        ctrl_tokens = encoders.ctrl(rgb)               # 1 encode (chỉ control)
                        target_tokens = goal_tokens
                        tag = "ctrl-only"
                    else:
                        nav, ctrl_tokens = encoders.both(rgb)          # 1 encode → cả nav + control
                        gps = None
                        if meta.get("lat", 0) and meta.get("lon", 0):
                            gps = (float(meta["lat"]), float(meta["lon"]))
                        cur = graph.localize(nav, gps_prior=gps)
                        # SAFETY off-route: node localize lệch GPS xe quá xa = lạc / localize sai →
                        # neutral thay vì lái theo route bịa (A4). Chỉ khi có GPS fix.
                        if gps is not None:
                            loc_err = float(np.linalg.norm(graph.to_xy(*gps) - graph.XY[cur]))
                            if loc_err > args.off_route_m:
                                emit(0.0, 0.0); prev_steer = 0.0
                                print(f"[infer] OFF-ROUTE: localize lệch GPS {loc_err:.1f}m > "
                                      f"{args.off_route_m}m -> neutral", flush=True)
                                time.sleep(period); continue
                        # reached? GPS distance to goal node — robust outdoors. Visual cosine aliases
                        # badly in self-similar parks (was firing instantly), so we DON'T use it.
                        gps_dist = None
                        if gps is not None:
                            gps_dist = float(np.linalg.norm(graph.to_xy(*gps) - graph.XY[goal_node]))
                            reached_now = gps_dist < args.reach_m
                        else:
                            reached_now = (cur == goal_node)
                        if reached_now:
                            emit(0.0, 0.0); reached = True
                            print(f"[infer] GOAL reached (gps_dist={gps_dist}) -> neutral"); break
                        route = graph.plan_route(cur, goal_node)
                        if not route:
                            emit(0.0, 0.0)
                            print(f"[infer] no route {cur}->{goal_node}; neutral"); time.sleep(period); continue
                        subs = graph.extract_subgoals(route, spacing_m=args.subgoal_spacing)
                        # FIX B: nhắm subgoal đầu tiên còn cách xe > advance_m (bỏ qua subgoal đã tới
                        # gần) → target luôn nằm PHÍA TRƯỚC, chống kẹt local-minimum (CEM hết "tưởng tới rồi").
                        if gps is not None:
                            car_xy = graph.to_xy(*gps)
                            ahead = [s for s in subs[1:]
                                     if float(np.linalg.norm(car_xy - graph.XY[s])) > args.advance_m]
                            target = ahead[0] if ahead else goal_node
                        else:
                            target = subs[1] if len(subs) >= 2 else subs[-1]
                        target_tokens = subgoal_patch(target)
                        gd = f"{gps_dist:.1f}m" if gps_dist is not None else "no-gps"
                        tag = f"cur{cur}->sub{target}->goal{goal_node} d={gd} route{len(subs)}"

                    z0 = ctrl_tokens.unsqueeze(0)                      # (1, N, D) — đã encode ở trên
                    s0 = build_state(meta, cols)
                    # bf16 autocast quanh CEM (mặc định fp32 → chậm); model train bf16 nên nhất quán.
                    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                        raw_steer, throt = planner.plan(z0, s0, target_tokens)
                    raw_steer, throt = float(raw_steer), float(throt)
                    # EMA làm mượt lái (chống zigzag/văng đường) + cua thì giảm ga
                    steer = args.steer_smooth * prev_steer + (1.0 - args.steer_smooth) * raw_steer
                    prev_steer = steer
                    throt = throt * (1.0 - args.turn_slow * min(1.0, abs(steer)))
                    emit(steer, throt)                                 # once (phone keeps-alive) or holder (dongle)
                    print(f"[infer] seq{seq} {tag} steer{steer:+.2f}(raw{raw_steer:+.2f}) throt{throt:+.2f} "
                          f"({time.time()-t0:.2f}s)", flush=True)

                    dtw = period - (time.time() - t0)
                    if dtw > 0:
                        time.sleep(dtw)
            except Exception as e:
                print(f"[infer] loop error: {e}")
            finally:
                reader.alive = False
                if holder is not None:
                    holder.stop()                   # dongle: stop keep-alive + neutral
                else:
                    try:
                        sender.send(0.0, 0.0)       # phone: one neutral (phone keep-alive will go stale)
                    except Exception:
                        pass
                conn.close()
                print(f"[infer] phone disconnected{' (goal reached)' if reached else ''}; waiting…")
    except KeyboardInterrupt:
        print("\n[infer] bye")
    finally:
        if dongle:
            dongle.stop(); dongle.close()
        srv.close()


if __name__ == "__main__":
    main()
