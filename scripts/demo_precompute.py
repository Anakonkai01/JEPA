#!/usr/bin/env python3
"""Precompute OPEN-LOOP energy-landscape demo data for ONE session → data/demo/<session>/demo.json.

For each frame t of a (held-out) session, goal = patch map d steps ahead in the SAME session;
hold throttle = teacher and sweep steer over [-1,1] → energy curve E(steer). Scoring is COPIED
verbatim from scripts/probe_energy.py (same planner.score call) so the aggregate numbers match
the validated probe (median contrast ~0.41, sign-turn ~96%). The web demo (demo_web.py) just
plays this JSON back — NO GPU / PyTorch at demo time.

Honesty: this is OPEN-LOOP. We do NOT roll the model's own action; the recorded video follows
the human driver. We only ask, per real frame: "to reach a waypoint ~{d*stride*0.11:.1f}s ahead,
how should you steer now?" and compare the planner's argmin-energy steer to the human's.

    PYTHONPATH=src python scripts/demo_precompute.py session_20260607_152325
    PYTHONPATH=src python scripts/demo_precompute.py session_20260607_152325 -d 4
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from jepa_wm.data.ac_clip import ACClipDataset
from jepa_wm.data.dataset import frozen_split
from jepa_wm.models import build_model
from jepa_wm.planning import CEMPlannerAC
from jepa_wm.planning.dynamics import CarDynamics

TURN = 0.15  # |steer| > TURN counts as "the human was turning" (same as probe_energy)


def _strip_compile(sd):
    return {k.replace("_orig_mod.", "", 1): v for k, v in sd.items()}


def _read_fidx(raw_dir, s):
    """frame_idx column of actions_synced.csv → maps a window row to frames/<idx>.jpg."""
    with open(Path(raw_dir) / s / "actions_synced.csv") as f:
        rows = list(csv.DictReader(f))
    return np.array([int(r["frame_idx"]) for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("-d", "--distance", type=int, default=4, help="goal = d bước phía trước (~0.9s)")
    ap.add_argument("--grid", type=int, default=21, help="số điểm quét steer trong [-1,1]")
    ap.add_argument("--grid-thr", type=int, default=19, help="số điểm quét throttle (landscape ga)")
    ap.add_argument("--thr-min", type=float, default=-0.1, help="ga thấp nhất khi quét (lùi nhẹ)")
    ap.add_argument("--thr-max", type=float, default=0.25, help="ga cao nhất khi quét (tiến)")
    ap.add_argument("--dt", type=float, default=0.22)
    ap.add_argument("--history", type=int, default=2)
    ap.add_argument("--out", default=None, help="mặc định data/demo/<session>/demo.json")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    # ---- load model + planner (copied from probe_energy.py) -------------------------------
    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict(_strip_compile(ckpt["model"]))
    model.eval()
    state_mean = ckpt["state_mean"].to(args.device).float()
    state_std = ckpt["state_std"].to(args.device).float()

    d_ = cfg["data"]
    roots = d_.get("roots")
    use_domain = roots is not None and (len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots))
    cols = tuple(d_.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    stride = d_.get("frame_stride", 2)
    ascale = tuple(d_.get("action_scale", [1.0, 6.67]))
    speed_idx = cols.index("speed") if "speed" in cols else 0
    yaw_idx = cols.index("gz") if "gz" in cols else 1
    prev_idx = (cols.index("prev_steer"), cols.index("prev_throttle")) if "prev_steer" in cols else None

    for r in roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    sessions = sorted(s for r in roots for s in r["_sessions"])
    split_path = Path(args.checkpoint).parent / "split.json"
    train_s, val_s, _ = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                     seed=cfg.get("seed", 0), save=False)
    train_set, val_set = set(train_s), set(val_s)
    is_val = args.session in val_set

    root = next((r for r in roots if args.session in r["_sessions"]), None)
    if root is None:
        raise SystemExit(f"session {args.session!r} không có patch .npy trong roots của checkpoint")

    dyn = CarDynamics.fit([(r["raw_dir"], [s for s in r["_sessions"] if s in train_set]) for r in roots],
                          dt=args.dt, stride=stride, speed_idx=speed_idx, yaw_idx=yaw_idx)
    d = args.distance
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=d, history=args.history, prev_action_idx=prev_idx,
                           device=args.device)

    # ---- one session, contiguous windows --------------------------------------------------
    ds = ACClipDataset(roots=[{"patch_dir": root["patch_dir"], "raw_dir": root["raw_dir"],
                               "sessions": [args.session], "domain_id": root.get("domain_id", 0)}],
                       horizon=d + 1, frame_stride=stride, state_columns=cols,
                       action_scale=(1.0, 1.0), state_mean=None, max_gap=d_.get("max_gap"))
    if len(ds) == 0:
        raise SystemExit(f"{args.session}: 0 window (session quá ngắn cho d={d}?)")
    fidx = _read_fidx(root["raw_dir"], args.session)
    grid = torch.linspace(-1.0, 1.0, args.grid)
    grid_np = grid.numpy()
    grid_thr = torch.linspace(args.thr_min, args.thr_max, args.grid_thr)
    grid_thr_np = grid_thr.numpy()

    frames_out = []
    derr, contrasts, contrasts_turn, contrasts_thr = [], [], [], []
    sign_ok_n = sign_tot_n = 0
    for k in range(len(ds)):
        _, i = ds.index[k]
        item = ds[k]
        z = item["tokens"].to(args.device).float()
        s0 = item["states"][0].to(args.device).float()
        a_raw = item["actions"].float()
        dom = float(a_raw[0, -1]) if use_domain else None
        tea = float(a_raw[:d, 0].mean())
        thr = float(a_raw[:d, 1].mean())
        seqs = torch.zeros(args.grid, d, 2, device=args.device)
        seqs[:, :, 0] = grid[:, None].to(args.device)
        seqs[:, :, 1] = thr
        # throttle landscape: hold steer = teacher, sweep throttle (so we can show ga too)
        seqs_t = torch.zeros(args.grid_thr, d, 2, device=args.device)
        seqs_t[:, :, 0] = tea
        seqs_t[:, :, 1] = grid_thr[:, None].to(args.device)
        with torch.no_grad():
            E = planner.score(z[:1], s0, z[d], seqs, domain=dom).cpu().numpy()
            E_thr = planner.score(z[:1], s0, z[d], seqs_t, domain=dom).cpu().numpy()
        kbest = int(np.argmin(E))
        best = float(grid_np[kbest])
        best_thr = float(grid_thr_np[int(np.argmin(E_thr))])
        contrast = float((E.max() - E.min()) / (E.min() + 1e-9))
        contrast_t = float((E_thr.max() - E_thr.min()) / (E_thr.min() + 1e-9))
        contrasts_thr.append(contrast_t)
        is_turn = abs(tea) > TURN
        sign_ok = bool(np.sign(best) == np.sign(tea)) if is_turn else None
        derr.append(abs(best - tea))
        contrasts.append(contrast)
        if is_turn:
            sign_tot_n += 1
            sign_ok_n += int(sign_ok)
            contrasts_turn.append(contrast)
        frames_out.append({
            "k": k,
            "cur_frame": int(fidx[i]),
            "goal_frame": int(fidx[i + d * stride]),
            "human_steer": round(tea, 4),
            "human_throttle": round(thr, 4),
            "model_steer": round(best, 4),
            "model_throttle": round(best_thr, 4),
            "contrast": round(contrast, 4),
            "contrast_thr": round(contrast_t, 4),
            "is_turn": is_turn,
            "sign_ok": sign_ok,
            "E": [round(float(x), 5) for x in E],
            "E_thr": [round(float(x), 5) for x in E_thr],
        })

    summary = {
        "n": len(frames_out),
        "n_turn": sign_tot_n,
        "sign_correct_turn": sign_ok_n,
        "sign_total_turn": sign_tot_n,
        "sign_acc_turn": round(sign_ok_n / max(sign_tot_n, 1), 3),
        "median_abs_dsteer": round(float(np.median(derr)), 3),
        "median_contrast": round(float(np.median(contrasts)), 3),
        "median_contrast_turn": round(float(np.median(contrasts_turn)), 3) if contrasts_turn else None,
        "median_contrast_thr": round(float(np.median(contrasts_thr)), 3) if contrasts_thr else None,
        "is_val": is_val,
    }
    out = {
        "session": args.session,
        "d": d, "stride": stride, "dt": args.dt,
        "goal_lead_s": round(d * stride * 0.11, 2),
        "grid": [round(float(x), 4) for x in grid_np],
        "grid_thr": [round(float(x), 4) for x in grid_thr_np],
        "is_val": is_val,
        "summary": summary,
        "frames": frames_out,
    }
    out_path = Path(args.out) if args.out else Path("data/demo") / args.session / "demo.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out))
    s = summary
    print(f"[demo] {args.session} (VAL={is_val}, d={d}=~{out['goal_lead_s']}s) → {out_path}")
    print(f"  n={s['n']}  turns={s['n_turn']}  sign-turn={s['sign_correct_turn']}/{s['sign_total_turn']}"
          f" ({s['sign_acc_turn']})  |Δsteer|med={s['median_abs_dsteer']}"
          f"  contrast med={s['median_contrast']} (turn {s['median_contrast_turn']})")
    print(f"  [gate] so với probe toàn-VAL: contrast~0.41 (turn 0.34), sign-turn~0.96")


if __name__ == "__main__":
    main()
