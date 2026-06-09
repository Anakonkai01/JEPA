"""Per-frame proprioceptive STATE token for the V-JEPA-2-AC car model.

The car analogue of V-JEPA 2-AC's 7-D end-effector pose. The single-frame visual
latent carries steering (front wheels are visible) but NOT speed — so the state
token is where velocity enters the model (docs/VJEPA2_AC_CAR.md §2).

We default to a **location-invariant** motion state ``[speed, yaw_rate, ax]`` rather
than absolute GPS x/y: the predictor only needs how-the-view-will-change (velocity +
turn rate), and absolute position would overfit to this particular park. Absolute
``x,y,heading`` are still available (for the CEM bicycle-model integrator, §3).

Sources, all on the same phone clock:
  * ``imu_synced.csv`` — per-frame already: gz (yaw rate, rad/s), ax/ay (accel).
  * ``gps.csv`` — ~1 Hz: speed (m/s), bearing (deg), lat/lon -> local metres.

``load_state(session_dir, columns)`` returns ``(state (N,K) float32, frame_idx (N,))``
aligned 1:1 with ``actions_synced.csv`` rows. Normalisation (z-score) is the caller's
job (done with train-set statistics).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

# State = the FULL IMU (gyro gx/gy/gz + accel ax/ay/az + rotation-vector rx/ry/rz) + GPS
# speed, all LOCATION-INVARIANT (won't let the model memorise the park). We feed raw accel
# too (its constant-gravity part is removed by the z-score; its varying part is real signal)
# and the rotvec orientation (pitch/roll = car attitude on bumps/slopes; yaw≈heading is mildly
# place-correlated but kept) — "use everything, then ABLATE vs minimal [speed,gz]". We still
# EXCLUDE absolute GPS lat/lon/alt/bearing by default: those encode the place itself = real
# overfit, not just noise (lat/lon/heading remain available only for the CEM dynamics).
DEFAULT_COLUMNS = ("speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz")
ALL_COLUMNS = ("speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz", "yaw_rate",
               "prev_steer", "prev_throttle",   # action ở frame t-1 (P2: cho model biết lệnh đang giữ)
               "heading_sin", "heading_cos", "x", "y", "heading")


def _read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _latlon_to_local(lat, lon, lat0, lon0):
    """Equirectangular projection to metres around (lat0, lon0)."""
    R = 6_371_000.0
    x = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * R
    return x, y


def load_state(session_dir, columns=DEFAULT_COLUMNS):
    session_dir = Path(session_dir)
    acts = _read(session_dir / "actions_synced.csv")
    fidx = np.array([int(r["frame_idx"]) for r in acts])
    ft = np.array([float(r["t_scene_ms"]) for r in acts])
    # action ở frame t-1 (raw [-1,1]); prev[0]=0 (đầu session chưa có lệnh trước). z-score lo phía sau.
    steer = np.array([float(r["steering"]) for r in acts])
    throt = np.array([float(r["throttle"]) for r in acts])
    prev_steer = np.concatenate([[0.0], steer[:-1]]) if len(steer) else steer
    prev_throttle = np.concatenate([[0.0], throt[:-1]]) if len(throt) else throt

    # --- IMU (already per-frame & synced) -> map by frame_idx
    imu = {int(r["frame_idx"]): r for r in _read(session_dir / "imu_synced.csv")}
    def col(name):
        return np.array([float(imu[f][name]) if f in imu else 0.0 for f in fidx])
    gx, gy, gz = col("gx"), col("gy"), col("gz")
    yaw_rate = gz                                      # alias
    ax, ay, az = col("ax"), col("ay"), col("az")
    rx, ry, rz = col("rx"), col("ry"), col("rz")       # rotation-vector (orientation)

    # --- GPS (~1 Hz) -> interpolate to frame scene-time
    gps = _read(session_dir / "gps.csv")
    gt = np.array([float(r["t_ms"]) for r in gps])
    order = np.argsort(gt); gt = gt[order]
    gsp = np.array([float(gps[i]["speed"]) for i in order])
    gbe = np.radians(np.array([float(gps[i]["bearing"]) for i in order]))
    lat = np.array([float(gps[i]["lat"]) for i in order])
    lon = np.array([float(gps[i]["lon"]) for i in order])

    speed = np.interp(ft, gt, gsp)
    # heading: interpolate via unit vector to handle the 0/2pi wrap
    hs = np.interp(ft, gt, np.sin(gbe)); hc = np.interp(ft, gt, np.cos(gbe))
    heading = np.arctan2(hs, hc)
    lat0, lon0 = lat[0], lon[0]
    xy = np.array([_latlon_to_local(la, lo, lat0, lon0) for la, lo in zip(lat, lon)])
    x = np.interp(ft, gt, xy[:, 0]); y = np.interp(ft, gt, xy[:, 1])

    avail = {"speed": speed, "gx": gx, "gy": gy, "gz": gz, "yaw_rate": yaw_rate,
             "ax": ax, "ay": ay, "az": az, "rx": rx, "ry": ry, "rz": rz,
             "prev_steer": prev_steer, "prev_throttle": prev_throttle,
             "heading_sin": hs, "heading_cos": hc, "x": x, "y": y, "heading": heading}
    state = np.stack([avail[c] for c in columns], axis=1).astype(np.float32)
    return state, fidx
