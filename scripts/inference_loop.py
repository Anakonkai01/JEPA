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

from jepa_wm.data.dataset import frozen_split  # noqa: E402
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

    def ctrl(self, rgb_u8):                               # one-off (subgoal / control-only)
        """1 forward → (raw pooled (1024,) — policy-prior input, tokens LN'd (576,1024) — CEM)."""
        tok = self._tokens(rgb_u8)
        return tok.mean(0), F.layer_norm(tok, (tok.size(-1),))


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


class WebBridge:
    """Cầu nối file-based với scripts/route_web.py (không đụng socket phone):
    - watch ``<dir>/active.json`` (web ghi): {"cmd":"run", waypoints..} / {"cmd":"stop"};
    - ghi ``<dir>/live_status.json`` + ``live_frame.jpg`` cho web hiển thị real-time."""

    def __init__(self, dir_):
        self.dir = Path(dir_)
        self.dir.mkdir(parents=True, exist_ok=True)
        # lệnh cũ từ phiên trước KHÔNG tự áp — chỉ nhận lệnh ghi SAU khi khởi động
        # (muốn chạy route: bấm ▶ Run lại trên web).
        try:
            self._mtime = (self.dir / "active.json").stat().st_mtime
            print(f"[web] active.json cũ bỏ qua — bấm ▶ Run trên web để giao route", flush=True)
        except OSError:
            self._mtime = 0.0
        self.route = None            # {"name","mode","waypoints","spacing"}
        self.wp_idx = 0
        self.stopped = False
        self._last_frame = 0.0

    def poll(self):
        p = self.dir / "active.json"
        try:
            mt = p.stat().st_mtime
        except OSError:
            return
        if mt <= self._mtime:
            return
        self._mtime = mt
        try:
            cmd = json.loads(p.read_text())
        except Exception:
            return
        if cmd.get("cmd") == "stop":
            self.route, self.stopped = None, True
            print("[web] ⛔ STOP từ web → neutral, chờ route mới", flush=True)
        elif cmd.get("cmd") == "run" and (cmd.get("waypoints") or cmd.get("subgoals")):
            self.route = {"name": str(cmd.get("name", "?")), "mode": str(cmd.get("mode", "graph")),
                          "waypoints": [int(w) for w in cmd.get("waypoints") or []],
                          "subgoals": list(cmd.get("subgoals") or []),
                          "spacing": float(cmd.get("spacing", 4.0))}
            self.wp_idx = 0
            self.stopped = False
            n = (len(self.route["subgoals"]) if self.route["mode"] == "manual"
                 else len(self.route["waypoints"]))
            print(f"[web] ▶ route '{self.route['name']}' (mode={self.route['mode']}, "
                  f"{n} {'subgoal tay' if self.route['mode'] == 'manual' else 'waypoint'})", flush=True)

    def status(self, **kw):
        kw["ts"] = time.time()
        if self.route:
            kw.setdefault("route", self.route["name"])
            kw.setdefault("mode", self.route["mode"])
            kw.setdefault("wp_idx", self.wp_idx)
            kw.setdefault("wp_total", len(self.route["subgoals"]) if self.route["mode"] == "manual"
                          else len(self.route["waypoints"]))
        tmp = self.dir / "live_status.tmp"
        tmp.write_text(json.dumps(kw))
        tmp.replace(self.dir / "live_status.json")

    def frame(self, rgb):
        now = time.time()
        if now - self._last_frame < 0.5:
            return
        self._last_frame = now
        cv2.imwrite(str(self.dir / "live_frame.jpg"), rgb[:, :, ::-1],
                    [int(cv2.IMWRITE_JPEG_QUALITY), 70])


# ---------------------------------------------------------------------------
def build_state(meta: dict, columns) -> torch.Tensor:
    """Raw state vector from stream meta, in the model's column order. gz==yaw_rate; prev-action =
    telemetry steering/throttle hiện tại (= lệnh đang áp = action 'trước' cho quyết định kế)."""
    alias = {"yaw_rate": "gz", "prev_steer": "steering", "prev_throttle": "throttle"}
    vals = [float(meta.get(alias.get(c, c), 0.0) or 0.0) for c in columns]
    return torch.tensor(vals, dtype=torch.float32)


def fit_dynamics(cfg, ckpt_path, speed_idx, yaw_idx, dt):
    """Fit CarDynamics on the model's TRAIN split (frozen split.json next to the ckpt,
    same as eval_goal_reaching_ac); supports both multi-root (data.roots) and legacy
    single-root cfg. Falls back to unit coeffs if data missing — but warns LOUDLY,
    because unit coefficients are far off the fitted ones (~1.8/0.09/0.14)."""
    try:
        d = cfg["data"]
        roots = d.get("roots") or [{"patch_dir": d["patch_dir"], "raw_dir": d["raw_dir"]}]
        for r in roots:
            r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
        sessions = sorted(s for r in roots for s in r["_sessions"])
        split_path = Path(ckpt_path).parent / "split.json"
        train_s, _, _ = frozen_split(split_path, sessions, val_frac=d.get("val_frac", 0.2),
                                     seed=cfg.get("seed", 0), save=False)
        tset = set(train_s)
        pairs = [(r["raw_dir"], [s for s in r["_sessions"] if s in tset]) for r in roots]
        dyn = CarDynamics.fit(pairs, dt=dt, stride=d.get("frame_stride", 2),
                              speed_idx=speed_idx, yaw_idx=yaw_idx)
        print(f"[infer] dynamics (fit): {dyn}")
        return dyn
    except Exception as e:
        print(f"[infer] ⚠️ dynamics fit FAILED ({e}); dùng unit coeffs k=1 — SAI LỆCH LỚN so với "
              f"fit thật (~k_thr 1.8 / k_drag 0.09 / k_yaw 0.14). Kiểm tra data/latents path!")
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
    ap.add_argument("--ctrl-lookahead-m", type=float, default=2.5,
                    help="target ẢNH cho CEM = node trên route polyline cách xe ngần này (mét, "
                         "along-track, chỉ-tiến). Subgoal --subgoal-spacing chỉ còn là mốc nav/pop. "
                         "Goal ảnh 3-7m vượt tầm-với CEM (horizon 0.88s ≈ ~1m) → gradient yếu → "
                         "understeer ở cua. 0 = tắt (target = subgoal như cũ).")
    ap.add_argument("--advance-m", type=float, default=3.0,
                    help="nhắm subgoal đầu tiên còn cách xe > ngần này (mét) → bỏ qua subgoal đã tới gần, chống kẹt")
    ap.add_argument("--steer-smooth", type=float, default=0.6,
                    help="EMA lái: steer = α·cũ + (1-α)·mới. Cao = mượt hơn (chống zigzag/văng đường). 0=tắt")
    ap.add_argument("--turn-slow", type=float, default=0.5,
                    help="cua thì giảm ga: throt *= (1 - k·|steer|). 0=tắt")
    ap.add_argument("--stale-s", type=float, default=0.4,
                    help="không có frame mới quá ngần này (giây) → NEUTRAL (link khựng, đừng giữ lệnh cũ)")
    ap.add_argument("--reconnect-s", type=float, default=8.0,
                    help="không có frame mới quá ngần này giây → ĐÓNG kết nối phone hiện tại, quay về "
                         "accept. App hay mở KẾT NỐI MỚI khi đổi mạng/app nền (kết nối cũ nửa-chết "
                         "không FIN → loop kẹt đọc mãi, conn mới nằm backlog, web báo offline — 06-12).")
    ap.add_argument("--off-route-m", type=float, default=10.0,
                    help="node localize cách xe (GPS) xa hơn ngần này → coi như LẠC → neutral (đừng lái theo route bịa)")
    ap.add_argument("--reach-m", type=float, default=4.0,
                    help="tới đích khi GPS cách goal < ngần này (mét). Robust hơn cosine ở park tự-giống.")
    ap.add_argument("--manual-reach-cos", type=float, default=0.97,
                    help="route TAY (teach&repeat): subgoal không có GPS (indoor) coi là ĐẠT khi cosine "
                         "pooled-latent(view hiện tại, ảnh subgoal) ≥ ngưỡng này. Log in cos mỗi tick "
                         "để tune; park tự-giống thì đừng dựa cosine (dùng GPS).")
    ap.add_argument("--manual-near-cos", type=float, default=0.95,
                    help="route TAY không GPS, luật pop thứ 2: ĐÃ TỚI GẦN (cos ≥ near) mà subgoal KẾ "
                         "trông gần hơn RÕ RỆT (cos_next > cos + 0.02) → coi như đã qua. Chống kẹt khi "
                         "ngưỡng tuyệt đối không bao giờ đạt (lệch sáng). Park alias nặng (đo e2e 06-12: "
                         "cos giữa các CHỖ KHÁC NHAU 0.94–0.97) → outdoor đừng dựa cosine, dùng GPS. 0 = tắt.")
    ap.add_argument("--manual-timeout-s", type=float, default=60.0,
                    help="route TAY: 1 subgoal quá ngần này giây không đạt → DỪNG route chờ lệnh web "
                         "(an toàn indoor: không GPS = không có stuck-recovery). 0 = tắt.")
    ap.add_argument("--rate", type=float, default=5.0, help="max control Hz")
    ap.add_argument("--dongle", action="store_true", help="send via ESP-NOW dongle, not phone relay")
    ap.add_argument("--dt", type=float, default=0.22)
    ap.add_argument("--fp16-encoder", action="store_true",
                    help="encoder fp16 (~nửa VRAM, hướng tới <6GB cho laptop; mặc định bf16-autocast)")
    ap.add_argument("--domain-id", type=float, default=1.0,
                    help="domain token cho model multi-root (0=KDS, 1=TowerPro — servo HIỆN TẠI trên xe). "
                         "Chỉ dùng khi checkpoint train multi-root (action_dim=3); model cũ bỏ qua.")
    ap.add_argument("--policy", default=None,
                    help="GoalPolicyPrior ckpt (train_policy_prior.py) — PiJEPA-style warm-start CEM mu "
                         "từ policy BC → ít iter/sample hơn, lái mượt hơn. None = CEM thuần.")
    ap.add_argument("--warm-std", type=float, default=0.15,
                    help="sigma CEM khi có --policy warm-start, theo tỉ lệ nửa-box mỗi chiều "
                         "(PiJEPA clamp σ nhỏ quanh prior). Chỉ có tác dụng khi mu_init được truyền.")
    ap.add_argument("--pulse", action=argparse.BooleanOptionalAction, default=False,
                    help="pulse mode (sense-plan-act): áp action --pulse-move giây rồi NGẮT GA (giữ lái) "
                         "trong lúc encode+CEM → drift lúc tính ≈ 0, frame để plan gần như tĩnh. "
                         "Chống dao động/văng route khi trễ ~0.4s.")
    ap.add_argument("--kick-throttle", type=float, default=0.12,
                    help="ga đề-pa khi xe đứng yên mà planner muốn tiến (thắng ma sát tĩnh; "
                         "controller vẫn clamp +0.15). Recovery lùi 0.11 đi được -> tiến ~0.12.")
    ap.add_argument("--kick-s", type=float, default=0.8,
                    help="thời lượng pulse đề-pa (mode --pulse; pulse thường = --pulse-move)")
    ap.add_argument("--cruise-throttle", type=float, default=0.07,
                    help="sàn ga khi đang lăn dưới --cruise-speed (giữ trớn đều, hết surge-coast)")
    ap.add_argument("--cruise-speed", type=float, default=0.5,
                    help="m/s; trên tốc độ này thì thả ga cho planner quyết hoàn toàn")
    ap.add_argument("--floor-no-gps", action="store_true",
                    help="indoor/không GPS: vẫn áp sàn ga = --cruise-throttle (KHÔNG kick — không có "
                         "tín hiệu đứng-yên tin được khi thiếu GPS). Chỉnh --cruise-throttle/"
                         "--throttle-cap theo mặt sàn (sàn nhà trơn hơn cỏ).")
    ap.add_argument("--pulse-move", type=float, default=0.45,
                    help="pulse: thời gian chạy mỗi nhịp (giây) ≈ 1-2 bước model (dt 0.22)")
    ap.add_argument("--recover", action=argparse.BooleanOptionalAction, default=True,
                    help="tự RECOVERY khi kẹt (đâm tường / lao bờ cỏ): lệnh ga tiến mà GPS speed ~0 "
                         "quá --stuck-s giây → lùi + đánh lái ngược --recover-s giây → replan. "
                         "(maneuver giống ~160 sự kiện va-lùi-chỉnh người lái trong data)")
    ap.add_argument("--stuck-speed", type=float, default=0.15, help="dưới tốc độ này (m/s) coi là không nhúc nhích")
    ap.add_argument("--stuck-m", type=float, default=0.6,
                    help="kẹt = dịch chuyển GPS < ngần này (mét) trong cửa sổ --stuck-s giây "
                         "(detector dịch-chuyển, thay doppler speed vốn báo 0 khi bò chậm)")
    ap.add_argument("--stuck-s", type=float, default=2.0, help="kẹt liên tục quá ngần này (giây) → recovery")
    ap.add_argument("--stuck-recent-m", type=float, default=0.25,
                    help="chỉ coi là kẹt nếu tick GẦN NHẤT cũng không nhúc nhích (< ngần này mét) — "
                         "chặn 'lùi oan' đúng lúc xe vừa đề-pa (net-disp cửa sổ còn nhỏ nhưng xe ĐANG lăn)")
    ap.add_argument("--recover-throttle", type=float, default=-0.11,
                    help="ga lùi lúc recovery (clamp cứng [-0.16,0] ở controller)")
    ap.add_argument("--recover-s", type=float, default=1.2, help="thời gian lùi mỗi lần recovery (giây)")
    ap.add_argument("--recover-max", type=int, default=3,
                    help="quá ngần này lần recovery trong 60s → DỪNG HẲN chờ người (tránh loop phá xe)")
    ap.add_argument("--web", nargs="?", const="data/routes", default=None, metavar="DIR",
                    help="bật cầu nối web planner (scripts/route_web.py): nhận route/STOP từ "
                         "DIR/active.json, ghi live_status.json + live_frame.jpg. Không cần "
                         "--goal-* (route giao từ web; xe idle + localize trong lúc chờ).")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    if cv2 is None:
        ap.error("opencv-python required (pip install opencv-python)")
    if args.web and args.control_only:
        ap.error("--web đi với full-nav (cần graph) — không dùng cùng --control-only")

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

    # multi-root checkpoint (KDS+TowerPro) -> action_dim=3 with appended domain token
    need_domain = ("roots" in cfg["data"]) or cfg["model"].get("action_dim", 2) == len(ascale) + 1
    domain = float(args.domain_id) if need_domain else None
    if need_domain:
        print(f"[infer] multi-root model -> domain token = {domain:g} (0=KDS, 1=TowerPro)")

    enc = load_encoder(args.device)
    encoders = Encoders(enc, args.device, fp16=args.fp16_encoder)
    dyn = fit_dynamics(cfg, args.checkpoint, speed_idx, yaw_idx, args.dt)
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=args.horizon, n_samples=args.samples, n_elite=args.elite,
                           n_iter=args.iters, throttle_min=0.0,           # forward-only (no surprise reverse)
                           throttle_max=args.throttle_cap, warm_std=args.warm_std,
                           prev_action_idx=prev_idx, domain=domain, device=args.device)

    policy = None
    if args.policy:
        from jepa_wm.models.policy_prior import load_policy
        policy, pol_meta = load_policy(args.policy, device=args.device)
        print(f"[infer] policy prior (PiJEPA warm-start): {args.policy} "
              f"(domain={'on' if pol_meta['use_domain'] else 'off'})")

    # --- goal ---
    graph = goal_node = goal_nav = goal_tokens = goal_pool = None
    subgoal_cache: dict[int, tuple] = {}

    def subgoal_patch(node: int) -> tuple:
        """node -> (raw pooled (1024,), LN tokens (N,D)) — one encode, cached."""
        if node not in subgoal_cache:
            img = cv2.imread(str(graph.frame_path(node)))
            if img is None:
                raise FileNotFoundError(f"subgoal frame missing: node {node}")
            subgoal_cache[node] = encoders.ctrl(img[:, :, ::-1].copy())
        return subgoal_cache[node]

    manual_cache: dict[str, tuple] = {}

    def manual_patch(rel: str) -> tuple:
        """Ảnh subgoal route TAY (path tương đối thư mục --web)
        -> (pool raw tensor, LN tokens, pool L2-normalized np — cho cosine-reach)."""
        p = Path(args.web) / rel
        # key kèm mtime: undo + 📸 lại ghi đè cùng tên file → không được trả cache cũ
        key = (rel, p.stat().st_mtime if p.exists() else -1.0)
        if key not in manual_cache:
            img = cv2.imread(str(p))
            if img is None:
                raise FileNotFoundError(f"manual subgoal missing: {p}")
            pool, tokens = encoders.ctrl(img[:, :, ::-1].copy())
            pn = pool.cpu().numpy().astype(np.float32)
            pn = pn / (np.linalg.norm(pn) + 1e-8)
            manual_cache[key] = (pool, tokens, pn)
        return manual_cache[key]

    if args.control_only:
        if not args.goal_image:
            ap.error("--control-only cần --goal-image")
        g = cv2.imread(args.goal_image)
        if g is None:
            ap.error(f"cannot read --goal-image {args.goal_image}")
        goal_pool, goal_tokens = encoders.ctrl(g[:, :, ::-1].copy())   # fixed CEM target
        print("[infer] CONTROL-ONLY: CEM lái thẳng tới ảnh goal (bỏ graph/nav). Chạy trong nhà OK, "
              "nhưng model train ở park → OOD, action có thể không chuẩn.")
    else:
        if args.graph and args.graph != "none" and Path(args.graph).exists():
            graph = TopoGraph.load(args.graph)
        elif args.web:
            print(f"[infer] KHÔNG có graph ({args.graph}) → manual-only: chỉ chạy ROUTE TAY "
                  f"(teach & repeat) từ web — indoor/chỗ mới. Route graph/direct + goal CLI bị từ chối.")
        else:
            ap.error(f"không thấy graph {args.graph} — full-nav cần graph "
                     f"(hoặc --web route tay, hoặc --control-only)")
        if graph is None:
            if args.goal_node is not None or args.goal_xy or args.goal_image:
                ap.error("--goal-node/--goal-xy/--goal-image cần graph — manual-only chỉ nhận route tay từ web")
        elif args.goal_node is not None:                       # chọn thẳng node trên graph
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
        elif not args.web:
            ap.error("full-nav cần --goal-node HOẶC --goal-image (hoặc --web để giao route từ web)")
        if goal_node is not None:
            goal_nav = graph.Zn[goal_node]                     # L2-normalised
            print(f"[infer] GOAL = node {goal_node} "
                  f"(session {graph.node_session[goal_node]} frame {graph.node_frame[goal_node]}, "
                  f"GPS xy {graph.XY[goal_node].round(1)})")
        else:
            print("[infer] chưa có goal — chờ route từ web (route_web.py → ▶ Run)")

    # --- TCP server: phone connects (client) ---
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"[infer] listening 0.0.0.0:{args.port} — set phone PC_HOST to this PC. "
          f"{'CONTROL-ONLY' if args.control_only else f'goal=node {goal_node}'}.")

    dongle = ctl.SerialDongleSender() if args.dongle else None
    web = WebBridge(args.web) if args.web else None
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

            def hold(s, t, secs):
                """Giữ action trong `secs` giây, resend ~3Hz (app ngừng keep-alive sau 1s PC im lặng)."""
                end = time.time() + secs
                while time.time() < end:
                    emit(s, t)
                    time.sleep(min(0.3, max(0.0, end - time.time())))

            reader = FrameReader(conn); reader.start()
            last_seq, reached, prev_steer = -1, False, 0.0
            last_frame_t = time.time()
            recover_times, halted, halted_route = [], False, None
            nav_subs, nav_goal = None, None               # route cache (Dijkstra 1 lần/goal)
            nav_route, route_cum, route_seg = None, None, 0   # polyline route + arc-length (lookahead)
            pos_hist = []                                 # (t, xy) cho stuck-detector dịch chuyển
            # route TAY: dwell cosine, đồng hồ timeout per-subgoal, route đang bám (reset khi giao mới)
            manual_hits, manual_last_idx, manual_t0, last_rt_obj = 0, -1, time.time(), None
            last_nf_status = 0.0                          # throttle ghi status "no-frame" (1Hz)
            try:
                while reader.alive:
                    if halted:                            # quá recover-max lần kẹt → đứng yên chờ người
                        emit(0.0, 0.0)
                        if web is not None:
                            web.poll()                    # vẫn nghe web: ▶ Run route mới = gỡ halt
                            web.status(state="halted")
                            if web.route is not None and web.route is not halted_route:
                                halted, recover_times = False, []
                                pos_hist.clear()
                                print("[infer] ▶ route mới từ web — gỡ DỪNG HẲN, chạy tiếp", flush=True)
                                continue
                        time.sleep(0.5); continue
                    t0 = time.time()
                    seq, item = reader.latest()
                    if item is None or seq == last_seq:
                        # SAFETY: link/stream khựng > stale_s → neutral (đừng để keep-alive giữ lệnh cũ)
                        now = time.time()
                        if now - last_frame_t > args.stale_s:
                            emit(0.0, 0.0); prev_steer = 0.0
                        # ngưỡng status TÁCH khỏi stale_s (0.4s): idle ngủ 0.5s/tick sẽ flap
                        if (web is not None and now - last_frame_t > 2.0
                                and now - last_nf_status > 1.0):
                            last_nf_status = now              # web hiện "no-frame" thay vì offline mù mờ
                            web.status(state="no-frame", seq=last_seq)
                        if now - last_frame_t > args.reconnect_s:
                            # phone mở kết nối MỚI khi đổi mạng/app nền mà không FIN cái cũ →
                            # reader kẹt recv vô hạn, conn mới chờ ở backlog → đóng conn này,
                            # vòng ngoài accept() nhận conn mới ngay (tự hồi, khỏi restart).
                            print(f"[infer] không có frame {args.reconnect_s:.0f}s → đóng kết nối, "
                                  f"chờ phone nối lại…", flush=True)
                            break
                        time.sleep(0.01); continue
                    last_seq = seq; last_frame_t = time.time()
                    meta, rgb = item
                    car_xy = None      # gán ở nhánh full-nav khi có GPS; ctrl-only luôn None
                                       # (trước đây ctrl-only chưa từng gán → recovery NameError)

                    if web is not None:
                        web.poll()                        # nhận route mới / STOP từ web
                        if web.stopped:
                            emit(0.0, 0.0); prev_steer = 0.0
                            web.frame(rgb)
                            web.status(state="stopped", seq=seq)
                            time.sleep(0.3); continue

                    if args.control_only:
                        cur_pool, ctrl_tokens = encoders.ctrl(rgb)     # 1 encode (chỉ control)
                        t_enc = time.time()
                        target_pool, target_tokens = goal_pool, goal_tokens
                        tag = "ctrl-only"
                    elif web is not None and web.route and web.route["mode"] == "manual":
                        # ---------- ROUTE TAY (teach & repeat, kiểu ViNG): bám chuỗi ảnh user 📸
                        # qua web — không cần graph, chạy được chỗ mới/indoor. Reach: GPS khi cả
                        # subgoal lẫn xe có toạ độ (teach ngoài trời); không GPS → cosine pooled.
                        # Cosine TUYỆT ĐỐI từng alias ở park (cao dù còn xa goal) nên thêm luật
                        # "đã GẦN (≥near) mà subgoal KẾ trông gần hơn = đã qua", dwell 2 tick,
                        # và timeout an toàn (indoor không GPS = không có stuck-recovery).
                        rt = web.route
                        wp_mode, cur = "manual", None
                        nav, ctrl_tokens = encoders.both(rgb)
                        t_enc = time.time()
                        cur_pool = torch.from_numpy(nav).to(args.device)
                        gps = None
                        if meta.get("lat", 0) and meta.get("lon", 0):
                            gps = (float(meta["lat"]), float(meta["lon"]))
                        car_xy = graph.to_xy(*gps) if (graph is not None and gps is not None) else None
                        if rt is not last_rt_obj:             # route mới giao → reset dwell/đồng hồ
                            last_rt_obj, manual_hits, manual_last_idx = rt, 0, -1
                        subs = rt["subgoals"]
                        navn = nav / (np.linalg.norm(nav) + 1e-8)
                        try:
                            def _mcos(i):                     # cosine(view hiện tại, subgoal i)
                                return float(navn @ manual_patch(subs[i]["img"])[2])

                            # pop GPS: ảnh chụp có thể dày hơn reach-m → pop hết các sub đã trong bán kính
                            while (web.wp_idx < len(subs) and car_xy is not None
                                   and subs[web.wp_idx].get("xy") is not None
                                   and float(np.linalg.norm(car_xy - np.asarray(
                                       subs[web.wp_idx]["xy"], np.float32))) < args.reach_m):
                                print(f"[web] ✓ subgoal tay {web.wp_idx + 1}/{len(subs)} (GPS)", flush=True)
                                web.wp_idx += 1; manual_hits = 0
                            cos_v = gps_dist = None
                            if web.wp_idx < len(subs):
                                sub = subs[web.wp_idx]
                                cos_v = _mcos(web.wp_idx)
                                if sub.get("xy") is not None and car_xy is not None:
                                    gps_dist = float(np.linalg.norm(car_xy - np.asarray(sub["xy"], np.float32)))
                                else:
                                    cos_next = _mcos(web.wp_idx + 1) if web.wp_idx + 1 < len(subs) else None
                                    # margin 0.02: park đo được cos giữa các chỗ KHÁC nhau lệch ~0.01-0.03
                                    # → margin nhỏ pop oan (e2e 06-12); cần "gần hơn RÕ RỆT" mới tin
                                    hit = cos_v >= args.manual_reach_cos or (
                                        args.manual_near_cos > 0 and cos_next is not None
                                        and cos_v >= args.manual_near_cos and cos_next > cos_v + 0.02)
                                    manual_hits = manual_hits + 1 if hit else 0
                                    if manual_hits >= 2:      # 2 tick liên tiếp — chống alias 1 frame
                                        nxt = f" next{cos_next:.3f}" if cos_next is not None else ""
                                        print(f"[web] ✓ subgoal tay {web.wp_idx + 1}/{len(subs)} "
                                              f"(cos {cos_v:.3f}{nxt})", flush=True)
                                        web.wp_idx += 1; manual_hits = 0
                                        if web.wp_idx < len(subs):
                                            cos_v = _mcos(web.wp_idx)
                            if web.wp_idx >= len(subs):       # hết chuỗi ảnh → xong route
                                emit(0.0, 0.0); prev_steer = 0.0
                                print(f"[web] 🏁 route tay '{rt['name']}' HOÀN THÀNH "
                                      f"({len(subs)} subgoal)", flush=True)
                                web.frame(rgb)
                                st = {"state": "reached", "seq": seq}
                                if car_xy is not None:
                                    st["xy"] = [float(car_xy[0]), float(car_xy[1])]
                                web.status(**st)
                                web.route = None
                                continue
                            if web.wp_idx != manual_last_idx:
                                manual_last_idx, manual_t0 = web.wp_idx, time.time()
                            if args.manual_timeout_s > 0 and time.time() - manual_t0 > args.manual_timeout_s:
                                emit(0.0, 0.0); prev_steer = 0.0
                                print(f"[web] ⏱ subgoal tay {web.wp_idx + 1}/{len(subs)} quá "
                                      f"{args.manual_timeout_s:.0f}s không đạt (cos {cos_v:.3f}) "
                                      f"→ DỪNG, chờ lệnh web", flush=True)
                                web.frame(rgb)
                                web.status(state="timeout", seq=seq)
                                web.route = None
                                continue
                            target_pool, target_tokens, _ = manual_patch(subs[web.wp_idx]["img"])
                        except FileNotFoundError as e:
                            emit(0.0, 0.0); prev_steer = 0.0
                            print(f"[web] ⚠ route tay thiếu ảnh ({e}) → STOP route", flush=True)
                            web.status(state="error", seq=seq)
                            web.route = None
                            continue
                        gd = f" d={gps_dist:.1f}m" if gps_dist is not None else ""
                        tag = f"manual {web.wp_idx + 1}/{len(subs)} cos{cos_v:.3f}{gd}"
                    else:
                        if graph is None:                     # manual-only (--graph none): teach/idle
                            if web.route is not None:
                                print(f"[web] ⚠ route '{web.route['name']}' mode={web.route['mode']} "
                                      f"cần graph — chỉ route TAY chạy được khi --graph none", flush=True)
                                web.route = None
                            emit(0.0, 0.0)
                            web.frame(rgb)
                            web.status(state="idle", seq=seq)
                            time.sleep(0.5)
                            continue
                        nav, ctrl_tokens = encoders.both(rgb)          # 1 encode → cả nav + control
                        t_enc = time.time()
                        cur_pool = torch.from_numpy(nav).to(args.device)
                        gps = None
                        if meta.get("lat", 0) and meta.get("lon", 0):
                            gps = (float(meta["lat"]), float(meta["lon"]))
                        cur = graph.localize(nav, gps_prior=gps)
                        car_xy = graph.to_xy(*gps) if gps is not None else None

                        # --- goal của vòng này: route từ WEB (waypoint tuần tự) > goal CLI ---
                        goal, wp_mode, spacing = goal_node, "graph", args.subgoal_spacing
                        if web is not None and web.route:
                            wpts = web.route["waypoints"]
                            wp_mode, spacing = web.route["mode"], web.route["spacing"]
                            # waypoint trung gian đã tới gần → sang cái tiếp theo (theo thứ tự user vẽ)
                            while (web.wp_idx < len(wpts) - 1 and car_xy is not None and
                                   float(np.linalg.norm(car_xy - graph.XY[wpts[web.wp_idx]])) < args.reach_m):
                                web.wp_idx += 1
                                print(f"[web] ✓ waypoint {web.wp_idx}/{len(wpts)} → node "
                                      f"{wpts[web.wp_idx]}", flush=True)
                            goal = wpts[web.wp_idx]
                        elif goal is None:                     # --web idle: localize + status, không lái
                            emit(0.0, 0.0)
                            web.frame(rgb)
                            xy = car_xy if car_xy is not None else graph.XY[cur]
                            web.status(state="idle", seq=seq, cur=int(cur),
                                       xy=[float(xy[0]), float(xy[1])])
                            time.sleep(0.5)
                            continue

                        # SAFETY off-route (mode graph): localize lệch GPS xe quá xa = lạc / localize
                        # sai. Trước khi neutral, ÉP localize lại trong bán kính off_route quanh GPS
                        # (gate mặc định 15m > off_route 10m → node visual 10-15m từng gây DEADLOCK:
                        # neutral → xe đứng → cảnh y nguyên → localize y nguyên, lặp vô hạn 06-11).
                        # Vẫn lệch sau khi ép = quanh GPS không có node nào (lạc thật) → neutral.
                        if wp_mode == "graph" and car_xy is not None:
                            loc_err = float(np.linalg.norm(car_xy - graph.XY[cur]))
                            if loc_err > args.off_route_m:
                                cur = graph.localize(nav, gps_prior=gps, gate_m=args.off_route_m)
                                loc_err = float(np.linalg.norm(car_xy - graph.XY[cur]))
                            if loc_err > args.off_route_m:
                                emit(0.0, 0.0); prev_steer = 0.0
                                print(f"[infer] OFF-ROUTE: localize lệch GPS {loc_err:.1f}m > "
                                      f"{args.off_route_m}m -> neutral", flush=True)
                                time.sleep(period); continue
                        # reached? GPS distance to goal node — robust outdoors. Visual cosine aliases
                        # badly in self-similar parks (was firing instantly), so we DON'T use it.
                        gps_dist = None
                        if car_xy is not None:
                            gps_dist = float(np.linalg.norm(car_xy - graph.XY[goal]))
                            reached_now = gps_dist < args.reach_m
                        else:
                            reached_now = (cur == goal)
                        if reached_now:
                            emit(0.0, 0.0); prev_steer = 0.0
                            if web is not None and web.route:   # web: xong route → chờ route mới
                                print(f"[web] 🏁 route '{web.route['name']}' HOÀN THÀNH "
                                      f"(gps_dist={gps_dist})", flush=True)
                                xy = car_xy if car_xy is not None else graph.XY[cur]
                                web.status(state="reached", seq=seq, cur=int(cur), goal=int(goal),
                                           xy=[float(xy[0]), float(xy[1])])
                                web.route = None
                                continue
                            reached = True
                            print(f"[infer] GOAL reached (gps_dist={gps_dist}) -> neutral"); break
                        if wp_mode == "direct":                # web direct: visual-servo THẲNG tới waypoint
                            target = goal
                            gd = f"{gps_dist:.1f}m" if gps_dist is not None else "no-gps"
                            tag = f"cur{cur}->WP{target} d={gd} direct"
                        else:
                            # ROUTE CACHE (A4 06-11): KHÔNG re-Dijkstra mỗi tick — localize flicker
                            # giữa các session song song (lệch ngang tới 8m) làm route/subgoal đổi
                            # liên tục → xe lượn. Plan 1 lần mỗi goal rồi BÁM chuỗi subgoal cố định,
                            # advance theo GPS; chỉ replan khi đổi goal / lạc tuyến (> off_route_m).
                            need_plan = nav_goal != goal or not nav_subs
                            if not need_plan and car_xy is not None:
                                d_near = min(float(np.linalg.norm(car_xy - graph.XY[s]))
                                             for s in nav_subs + [goal])
                                need_plan = d_near > args.off_route_m
                            if need_plan:
                                route = graph.plan_route(cur, goal)
                                if not route:
                                    emit(0.0, 0.0)
                                    print(f"[infer] no route {cur}->{goal}; neutral"); time.sleep(period); continue
                                sg = graph.extract_subgoals(route, spacing_m=spacing)
                                # bỏ node xuất phát (= chỗ xe đang đứng; lệch localize-GPS có thể
                                # >advance_m → nếu giữ, nó làm target vĩnh viễn: xe servo về ảnh
                                # điểm xuất phát, không quẹo — bug chạy thật 06-11)
                                nav_subs, nav_goal = (sg[1:] if len(sg) > 1 else sg), goal
                                nav_route = route
                                route_cum = (np.concatenate([[0.0], np.cumsum(np.linalg.norm(
                                    np.diff(graph.XY[route], axis=0), axis=1))])
                                             if len(route) > 1 else np.zeros(1))
                                route_seg = 0
                                print(f"[infer] route mới: {len(nav_subs)} subgoal (cur{cur}->goal{goal})", flush=True)
                            subs = nav_subs
                            # FIX B: bỏ hẳn subgoal đã QUA khỏi cache — "qua" = tới gần (≤advance_m)
                            # HOẶC subgoal kế đã gần hơn (vượt qua với độ lệch ngang lớn) → target
                            # luôn nằm PHÍA TRƯỚC, tiến độ đơn điệu (pop không quay lại).
                            if car_xy is not None:
                                def _d(n):
                                    return float(np.linalg.norm(car_xy - graph.XY[n]))
                                while len(nav_subs) > 1 and (_d(nav_subs[0]) <= args.advance_m
                                                             or _d(nav_subs[1]) < _d(nav_subs[0])):
                                    nav_subs.pop(0)
                                target = nav_subs[0] if _d(nav_subs[0]) > args.advance_m else goal
                            else:
                                target = subs[1] if len(subs) >= 2 else subs[-1]
                            # CONTROL-target gần (along-track): subgoal 4m chỉ là mốc NAV/pop;
                            # CEM horizon 0.88s với ~1m nên ảnh goal 3-7m cho gradient yếu →
                            # understeer ở cua. Chiếu xe lên polyline route (chỉ-tiến, cửa sổ 40
                            # segment) → target = node cách ~lookahead m phía trước (quantize 3
                            # node để target đứng yên vài tick → đỡ churn cache encode subgoal).
                            if (args.ctrl_lookahead_m > 0 and car_xy is not None
                                    and nav_route is not None and len(nav_route) >= 2):
                                P = graph.XY
                                best_d, best_seg, best_t = 1e18, route_seg, 0.0
                                for k in range(route_seg, min(route_seg + 40, len(nav_route) - 1)):
                                    a, b = P[nav_route[k]], P[nav_route[k + 1]]
                                    ab = b - a
                                    L2 = float(ab @ ab)
                                    tt = 0.0 if L2 < 1e-9 else float(np.clip(((car_xy - a) @ ab) / L2, 0.0, 1.0))
                                    dd = float(np.linalg.norm(car_xy - (a + tt * ab)))
                                    if dd < best_d:
                                        best_d, best_seg, best_t = dd, k, tt
                                route_seg = best_seg              # monotonic — không match lùi
                                s_along = route_cum[best_seg] + best_t * (route_cum[best_seg + 1] - route_cum[best_seg])
                                # đi dọc route tới target: dừng ở lookahead m HOẶC khi heading
                                # route đã xoay ~50° so với điểm chiếu → VÀO CUA TARGET TỰ DÀY LÊN
                                # (ảnh target luôn còn overlap với view hiện tại; goal "qua góc
                                # 90°" = không nhìn thấy = energy mù — bug user mô tả 06-11)
                                h0 = float(graph.heading[nav_route[best_seg]])
                                j = best_seg + 1
                                while j < len(nav_route) - 1:
                                    if route_cum[j] - s_along >= args.ctrl_lookahead_m:
                                        break
                                    dh = abs((float(graph.heading[nav_route[j]]) - h0 + np.pi)
                                             % (2 * np.pi) - np.pi)
                                    if dh >= 0.9:                 # ~50°
                                        break
                                    j += 1
                                target = nav_route[j]
                            gd = f"{gps_dist:.1f}m" if gps_dist is not None else "no-gps"
                            tag = f"cur{cur}->sub{target}->goal{goal} d={gd} route{len(subs)}"
                        target_pool, target_tokens = subgoal_patch(target)

                    t_tgt = time.time()
                    z0 = ctrl_tokens.unsqueeze(0)                      # (1, N, D) — đã encode ở trên
                    s0 = build_state(meta, cols)
                    # Tốc độ ước lượng = max(doppler, dịch-chuyển GPS từ pos_hist): doppler báo
                    # 0.00 khi bò → kick/kickstart từng bắn lúc xe VẪN LĂN (= surge 0.12 giữa cua,
                    # đúng chỗ dễ văng lề). Đứng yên thật thì cả hai ~0 → kick vẫn nguyên (đề-pa
                    # cần đủ lực, không bị turn_slow/cruise cắt).
                    spd_est = float(meta.get("speed", 0.0) or 0.0)
                    if car_xy is not None and pos_hist:
                        sp_h = time.time() - pos_hist[0][0]
                        if sp_h > 0.5:
                            spd_est = max(spd_est, float(np.linalg.norm(car_xy - pos_hist[0][1])) / sp_h)
                    # PiJEPA-style warm start: policy đề xuất action từ (pooled hiện tại, pooled goal,
                    # state) → khởi tạo mu của CEM (CEM vẫn refine dưới world model).
                    mu0 = None
                    if policy is not None:
                        s_z = ((s0.to(args.device) - state_mean) / state_std).unsqueeze(0)
                        with torch.no_grad():
                            mu0 = policy(cur_pool.float().unsqueeze(0), target_pool.float().unsqueeze(0),
                                         s_z, domain if pol_meta["use_domain"] else None)[0]
                        # Kickstart chống "standstill attractor" của BC prior: người lái lúc đứng yên
                        # đa số cũng ga ~0 → policy đề xuất ga ~0, mà warm-start σ nhỏ (~0.01) quanh 0
                        # thì CEM không thoát ra được (ga ~0.01 < ma sát tĩnh → xe đứng im / recovery
                        # lùi vô hạn). Xe đang đứng yên → ép mu ga ≥ 0.75·cap cho pulse đầu đủ lực;
                        # lăn bánh rồi thì policy điều ga bình thường.
                        if spd_est < args.stuck_speed:
                            mu0 = mu0.clone()
                            mu0[..., 1] = mu0[..., 1].clamp(min=0.75 * args.throttle_cap)
                    # bf16 autocast quanh CEM (mặc định fp32 → chậm); model train bf16 nên nhất quán.
                    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                        raw_steer, throt = planner.plan(z0, s0, target_tokens, mu_init=mu0)
                    t_plan = time.time()
                    raw_steer, throt = float(raw_steer), float(throt)
                    # EMA làm mượt lái (chống zigzag/văng đường) + cua thì giảm ga
                    steer = args.steer_smooth * prev_steer + (1.0 - args.steer_smooth) * raw_steer
                    prev_steer = steer
                    throt = throt * (1.0 - args.turn_slow * min(1.0, abs(steer)))
                    # BREAKAWAY + CRUISE (chạy thật 06-11): policy/CEM hay ra ga ~0 → xe chạy
                    # kiểu giật-trớn-giật toàn bằng cú kick (lái stale giữa các cú surge → lượn).
                    # 2 tầng: đứng yên → kick 0.12 thắng ma sát tĩnh (lùi recovery 0.11 đi được,
                    # tiến 0.07 pulse thì không); đang lăn dưới cruise_speed → sàn ga cruise 0.07
                    # giữ trớn ĐỀU để lái được sửa liên tục. Trên cruise_speed → ga planner.
                    kick = False
                    # Sàn ga áp VÔ ĐIỀU KIỆN khi đang lái theo goal (CEM box ga = [0,cap], không
                    # tồn tại "muốn lùi"; tới đích đã neutral ở reach-check phía trên). Gate cũ
                    # `throt>0.02` làm tick planner ra ~0 thì không floor → ga nhấp nhả 0.12/0.00
                    # xen kẽ → không tích trớn → dịch <0.6m/3s → recovery v2 lùi oan ("lùi quài").
                    # Tier chọn theo spd_est (max doppler/GPS-displacement) — doppler 0.00 khi bò
                    # từng xếp xe-đang-lăn vào tier kick → surge 0.12 giữa cua.
                    if args.floor_no_gps:
                        # indoor: CHỈ floor cruise, CẤM kick — đặt TRƯỚC nhánh GPS vì trong nhà
                        # phone vẫn hay còn GPS rác (lat≠0 gần cửa sổ) → từng kích kick 0.12
                        # trên sàn trơn thay vì cruise 0.04 (chạy thật 06-12)
                        throt = max(throt, args.cruise_throttle)
                    elif float(meta.get("lat", 0) or 0) != 0:
                        if spd_est < args.stuck_speed:
                            throt = max(throt, args.kick_throttle); kick = True
                        elif spd_est < args.cruise_speed:
                            throt = max(throt, args.cruise_throttle)
                    emit(steer, throt)                                 # once (phone keeps-alive) or holder (dongle)
                    print(f"[infer] seq{seq} {tag} steer{steer:+.2f}(raw{raw_steer:+.2f}) throt{throt:+.2f} "
                          f"({time.time()-t0:.2f}s enc{t_enc-t0:.2f} nav{t_tgt-t_enc:.2f} "
                          f"cem{t_plan-t_tgt:.2f})", flush=True)

                    if web is not None:                    # live cho web planner (map + camera)
                        web.frame(rgb)
                        st = {"state": "run", "seq": seq, "mode": wp_mode,
                              "steer": round(steer, 3), "throt": round(throt, 3)}
                        if car_xy is not None:
                            st["xy"] = [float(car_xy[0]), float(car_xy[1])]
                        elif cur is not None:              # không GPS nhưng có graph → xy node localize
                            st["xy"] = [float(graph.XY[cur][0]), float(graph.XY[cur][1])]
                        if gps_dist is not None:
                            st["gps_dist"] = round(float(gps_dist), 1)
                        if wp_mode == "manual":            # route tay: subgoal index + cosine (tune ngưỡng)
                            st["cos"] = round(cos_v, 3)
                        else:
                            st.update(cur=int(cur), goal=int(goal), target=int(target))
                        web.status(**st)

                    # --- STUCK / CRASH RECOVERY: lệnh ga tiến mà xe không nhúc nhích (đâm tường,
                    # lao bờ cỏ, kẹt bánh) → lùi + đánh lái ngược rồi replan (giống người lái trong data).
                    # Detector v2 theo DỊCH CHUYỂN GPS thật (06-11: doppler speed báo 0.00 cả khi
                    # đang bò → false positive lùi oan; còn lúc kẹt cỏ thật thì vị trí GPS đông cứng
                    # ±0.2m — tín hiệu sạch). Kẹt = đang lệnh tiến mà net-displacement < stuck_m
                    # trong cửa sổ stuck_s giây. Cần GPS fix (trong nhà tự tắt như cũ).
                    # v2.1 (06-11 đêm, validate OFFLINE bằng replay 340' GPS người lái —
                    # /tmp/replay_stuck_v2.py): v2 net-disp-từ-đầu-cửa-sổ bắn OAN 0.86 lần/phút
                    # (72% trigger xe đang/đi tiếp >1m) vì không phân biệt "kẹt 3s" với "đứng 2s
                    # rồi VỪA đề-pa"; còn prune >stuck_s làm span tối đa = 1 tick 1.36s < 0.7×2.0s
                    # → default --stuck-s 2.0 KHÔNG BAO GIỜ bắn. Fix 3 vế: (1) giữ 1 mẫu GIÀ hơn
                    # stuck_s → span luôn đủ; (2) phải ĐANG ĐẨY (throt>0.03) suốt cửa sổ — cú kick
                    # được trọn stuck_s chứng tỏ vô dụng rồi mới lùi; (3) tick gần nhất cũng phải
                    # đứng yên (< stuck_recent_m). Replay: oan 0.86→0.06/phút (~14×), giữ true-stuck.
                    if args.recover and car_xy is not None:
                        now = time.time()
                        pos_hist.append((now, car_xy, throt > 0.03))
                        while len(pos_hist) > 2 and now - pos_hist[1][0] > args.stuck_s:
                            pos_hist.pop(0)
                        moved = float(np.linalg.norm(car_xy - pos_hist[0][1]))
                        span = now - pos_hist[0][0]
                        recent = (float(np.linalg.norm(car_xy - pos_hist[-2][1]))
                                  if len(pos_hist) >= 2 else 9.9)
                        pushing_all = all(p[2] for p in pos_hist)
                        if (pushing_all and span >= args.stuck_s * 0.7 and moved < args.stuck_m
                                and recent < args.stuck_recent_m):
                            recover_times = [t for t in recover_times if now - t < 60.0]
                            if len(recover_times) >= args.recover_max:
                                halted = True
                                halted_route = web.route if web is not None else None
                                emit(0.0, 0.0)
                                print(f"[infer] 🛑 KẸT {args.recover_max} lần/60s — DỪNG HẲN, cần người "
                                      f"(gạt CH9 về manual để lấy xe).", flush=True)
                                continue
                            recover_times.append(now)
                            rev_steer = max(-1.0, min(1.0, -prev_steer))
                            print(f"[infer] 🔁 RECOVERY #{len(recover_times)}: dịch {moved:.2f}m/"
                                  f"{span:.1f}s → lùi {args.recover_s:.1f}s steer {rev_steer:+.2f} "
                                  f"throt {args.recover_throttle:+.2f}", flush=True)
                            hold(0.0, 0.0, 0.3)                       # khựng lại, nhả ESC
                            hold(rev_steer, args.recover_throttle, args.recover_s)
                            hold(0.0, 0.0, 0.3)                       # dừng → frame mới gần như tĩnh
                            pos_hist.clear()                          # re-arm detector sau cú lùi
                            prev_steer = 0.0                          # reset EMA lái, replan từ đầu
                            continue                                  # bỏ pacing, lấy frame mới ngay

                    if args.pulse:
                        # PULSE (sense-plan-act): cho xe CHẠY pulse_move giây với action vừa chốt,
                        # rồi NGẮT GA (giữ lái) — vòng sau encode+CEM trên cảnh gần như đứng yên,
                        # drift trong lúc tính ≈ 0 (trễ không còn ăn vào độ chính xác).
                        hold(steer, throt, args.kick_s if kick else args.pulse_move)
                        emit(steer, 0.0)                              # coast trong lúc tính
                    else:
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
