"""CarDynamics — forward integrator for the [speed, yaw_rate] state during CEM rollout.

At planning time the future states aren't observed, so (like V-JEPA 2-AC's
``compute_new_pose``) we integrate them from the candidate actions. Our state is the
location-invariant motion state ``[speed, yaw_rate]``; the dynamics are:

    speed'    = speed + (k_thr * throttle - k_drag * speed) * dt        (drive vs drag)
    yaw_rate' = k_yaw * steer * speed'                                  (bicycle: turn ∝ steer·speed)

Coefficients are FIT from recorded data (``CarDynamics.fit``): regress observed Δspeed on
(throttle, speed) and yaw_rate on (steer·speed). dt = clip frame-stride period (~0.22 s).
Action here is the RAW [steer, throttle] in [-1,1] units (NOT the train action_scale).
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import torch

from ..data.state import load_state


class CarDynamics:
    """Integrates the FULL state vector during CEM rollout. Only the two physically
    derivable channels are integrated from the action — speed (``speed_idx``) and yaw
    rate (``yaw_idx`` = the gz column) — the rest (accel, roll/pitch rate) are held at
    their current value (we can't predict future bumps from a steer/throttle command;
    over the short ~1 s horizon hold-last is a reasonable prior). ``speed_idx``/``yaw_idx``
    must match the position of speed / gz in the training ``state_columns``.
    """

    def __init__(self, k_thr=1.0, k_drag=1.0, k_yaw=1.0, dt=0.22, speed_idx=0, yaw_idx=3):
        self.k_thr, self.k_drag, self.k_yaw, self.dt = k_thr, k_drag, k_yaw, dt
        self.speed_idx, self.yaw_idx = speed_idx, yaw_idx

    def step(self, state, action):
        """state (...,S), action (...,2)=[steer,throttle] -> next state (...,S)."""
        speed = state[..., self.speed_idx]; steer = action[..., 0]; throttle = action[..., 1]
        speed_n = speed + (self.k_thr * throttle - self.k_drag * speed) * self.dt
        speed_n = speed_n.clamp_min(0.0) if torch.is_tensor(speed_n) else np.maximum(0.0, speed_n)
        yaw_n = self.k_yaw * steer * speed_n
        out = state.clone() if torch.is_tensor(state) else state.copy()
        out[..., self.speed_idx] = speed_n
        out[..., self.yaw_idx] = yaw_n
        return out

    @classmethod
    def fit(cls, raw_dir, sessions, dt=0.22, stride=2, speed_idx=0, yaw_idx=3):
        """Least-squares fit k_thr,k_drag,k_yaw from data at the clip frame-stride."""
        sp_cur, sp_nxt, thr, steer_sp, yaw = [], [], [], [], []
        for s in sessions:
            d = Path(raw_dir) / s
            try:
                st, fidx = load_state(d, ("speed", "yaw_rate"))
            except Exception:
                continue
            acts = {int(r["frame_idx"]): (float(r["steering"]), float(r["throttle"]))
                    for r in csv.DictReader(open(d / "actions_synced.csv"))}
            speed = st[:, 0]; yr = st[:, 1]
            for i in range(len(fidx) - stride):
                f = int(fidx[i])
                if f not in acts:
                    continue
                sp_cur.append(speed[i]); sp_nxt.append(speed[i + stride])
                str_, th_ = acts[f]
                thr.append(th_); steer_sp.append(str_ * speed[i + stride]); yaw.append(yr[i])
        sp_cur = np.array(sp_cur); sp_nxt = np.array(sp_nxt); thr = np.array(thr)
        # Δspeed = (k_thr*throttle - k_drag*speed)*dt  ->  regress Δspeed/dt on [throttle, -speed]
        dsp = (sp_nxt - sp_cur) / dt
        A = np.stack([thr, -sp_cur], axis=1)
        (k_thr, k_drag), *_ = np.linalg.lstsq(A, dsp, rcond=None)
        # yaw_rate = k_yaw * steer * speed
        steer_sp = np.array(steer_sp); yaw = np.array(yaw)
        k_yaw = float((steer_sp @ yaw) / max(steer_sp @ steer_sp, 1e-9))
        return cls(k_thr=float(k_thr), k_drag=float(k_drag), k_yaw=k_yaw, dt=dt,
                   speed_idx=speed_idx, yaw_idx=yaw_idx)

    def __repr__(self):
        return f"CarDynamics(k_thr={self.k_thr:.3f}, k_drag={self.k_drag:.3f}, k_yaw={self.k_yaw:.3f}, dt={self.dt})"
