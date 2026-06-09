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
    def __init__(self, enc, device, nav_size=384, ctrl_size=256):
        self.enc, self.device = enc, device
        self.nav_size, self.ctrl_size = nav_size, ctrl_size

    @torch.no_grad()
    def nav(self, rgb_u8) -> np.ndarray:
        """384px pooled latent (1024,) — same as build_graph nodes."""
        x = _to_tensor(rgb_u8, self.nav_size, self.device)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.startswith("cuda")):
            tok = self.enc(x)                                # (1, 576, 1024)
        return tok.float().mean(1)[0].cpu().numpy()

    @torch.no_grad()
    def ctrl(self, rgb_u8) -> torch.Tensor:
        """256px patch tokens (256,1024), per-token layer-normed (as ACClipDataset feeds)."""
        x = _to_tensor(rgb_u8, self.ctrl_size, self.device)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.startswith("cuda")):
            tok = self.enc(x)                                # (1, 256, 1024)
        z = tok.float()[0]
        return F.layer_norm(z, (z.size(-1),))                # (256, 1024)


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
    """Raw state vector from stream meta, in the model's column order. gz==yaw_rate."""
    alias = {"yaw_rate": "gz"}
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
    ap.add_argument("--goal-image", required=True, help="goal frame -> nearest graph node = goal")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--horizon", type=int, default=4, help="CEM (MPC) lookahead steps")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--elite", type=int, default=16)
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--subgoal-spacing", type=float, default=4.0, help="metres between subgoals")
    ap.add_argument("--reach-sim", type=float, default=0.85, help="cosine to a subgoal = reached")
    ap.add_argument("--rate", type=float, default=5.0, help="max control Hz")
    ap.add_argument("--dongle", action="store_true", help="send via ESP-NOW dongle, not phone relay")
    ap.add_argument("--dt", type=float, default=0.22)
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

    enc = load_encoder(args.device)
    encoders = Encoders(enc, args.device)
    graph = TopoGraph.load(args.graph)
    dyn = fit_dynamics(cfg, cols, speed_idx, yaw_idx, args.dt)
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=args.horizon, n_samples=args.samples, n_elite=args.elite,
                           n_iter=args.iters, throttle_min=ctl.THROTTLE_MIN,
                           throttle_max=ctl.THROTTLE_MAX, device=args.device)

    # --- goal node from the goal image ---
    goal_rgb = cv2.imread(args.goal_image)
    if goal_rgb is None:
        ap.error(f"cannot read --goal-image {args.goal_image}")
    goal_node = graph.localize(encoders.nav(goal_rgb[:, :, ::-1].copy()))
    goal_nav = graph.Zn[goal_node]                              # L2-normalised
    print(f"[infer] goal image -> node {goal_node} "
          f"(session {graph.node_session[goal_node]} frame {graph.node_frame[goal_node]})")

    subgoal_cache: dict[int, torch.Tensor] = {}

    def subgoal_patch(node: int) -> torch.Tensor:
        if node not in subgoal_cache:
            p = graph.frame_path(node)
            img = cv2.imread(str(p))
            if img is None:
                raise FileNotFoundError(f"subgoal frame missing: {p}")
            subgoal_cache[node] = encoders.ctrl(img[:, :, ::-1].copy())
        return subgoal_cache[node]

    # --- TCP server: phone connects (client) ---
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"[infer] listening 0.0.0.0:{args.port} — set phone PC_HOST to this PC. Goal=node {goal_node}.")

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
            last_seq, reached = -1, False
            try:
                while reader.alive:
                    t0 = time.time()
                    seq, item = reader.latest()
                    if item is None or seq == last_seq:
                        time.sleep(0.01); continue
                    last_seq = seq
                    meta, rgb = item

                    nav = encoders.nav(rgb)
                    gps = None
                    if meta.get("lat", 0) and meta.get("lon", 0):
                        gps = (float(meta["lat"]), float(meta["lon"]))
                    cur = graph.localize(nav, gps_prior=gps)

                    # reached goal? (visual cosine to the goal node)
                    navn = nav / (np.linalg.norm(nav) + 1e-8)
                    if cur == goal_node or float(goal_nav @ navn) >= args.reach_sim:
                        emit(0.0, 0.0); reached = True
                        print("[infer] GOAL reached -> neutral"); break

                    route = graph.plan_route(cur, goal_node)
                    if not route:
                        emit(0.0, 0.0)
                        print(f"[infer] no route {cur}->{goal_node}; neutral"); time.sleep(period); continue
                    subs = graph.extract_subgoals(route, spacing_m=args.subgoal_spacing)
                    target = subs[1] if len(subs) >= 2 else subs[-1]   # next subgoal ahead

                    z0 = encoders.ctrl(rgb).unsqueeze(0)               # (1, N, D)
                    s0 = build_state(meta, cols)
                    steer, throt = planner.plan(z0, s0, subgoal_patch(target))
                    emit(float(steer), float(throt))                   # once (phone keeps-alive) or holder (dongle)
                    print(f"[infer] seq{seq} cur{cur}->sub{target}->goal{goal_node} "
                          f"steer{float(steer):+.2f} throt{float(throt):+.2f} ({time.time()-t0:.2f}s)",
                          flush=True)

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
