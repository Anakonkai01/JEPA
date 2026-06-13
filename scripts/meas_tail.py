#!/usr/bin/env python3
"""Đo TAM GIÁC closed-loop (offline, VAL frozen): vì sao bãi đỏ dù offline-trung-vị xanh.
  H2 — phân bố ĐUÔI per-window: %window đoạn-thẳng có argminE ở BIÊN (full-lock bịa) +
       %window energy PHẲNG (contrast<0.1). Trung vị tốt nhưng đuôi giết closed-loop.
  H5 — argminE-vs-teacher theo bucket |steer|: predictor có bám hướng người lái cả ở
       cú-bẻ-LỚN (proxy recovery) không.
  H4 — CEM plan() ở samples {16..256} × nhiều seed: phương sai argmin + %full-lock trên
       đoạn thẳng GIẢM theo samples? (lượng-hoá "chậm/nhiều-sample thắng").

    PYTHONPATH=src python scripts/meas_tail.py
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import torch
from jepa_wm.data.ac_clip import ACClipDataset
from jepa_wm.data.dataset import frozen_split
from jepa_wm.models import build_model
from jepa_wm.planning import CEMPlannerAC
from jepa_wm.planning.dynamics import CarDynamics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("-d", "--distance", type=int, default=4)
    ap.add_argument("--n-windows", type=int, default=300)
    ap.add_argument("--n-cem", type=int, default=60, help="số window chạy H4 (CEM sample sweep)")
    ap.add_argument("--grid", type=int, default=21)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    ck = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ck["cfg"]
    model = build_model(cfg["model"]).to(args.device)
    model.load_state_dict({k.replace("_orig_mod.", "", 1): v for k, v in ck["model"].items()})
    model.eval()
    sm = ck["state_mean"].to(args.device).float(); ss = ck["state_std"].to(args.device).float()
    d_ = cfg["data"]; roots = d_["roots"]
    use_domain = len(roots) > 1 or any(int(r.get("domain_id", 0)) != 0 for r in roots)
    cols = tuple(d_.get("state_columns", ["speed", "gx", "gy", "gz", "ax", "ay", "az", "rx", "ry", "rz"]))
    stride = d_.get("frame_stride", 2); ascale = tuple(d_.get("action_scale", [1.0, 6.67]))
    spd_i = cols.index("speed"); yaw_i = cols.index("gz")
    prev_idx = (cols.index("prev_steer"), cols.index("prev_throttle")) if "prev_steer" in cols else None
    for r in roots:
        r["_sessions"] = sorted(p.stem for p in Path(r["patch_dir"]).glob("*.npy"))
    sessions = sorted(s for r in roots for s in r["_sessions"])
    train_s, val_s, _ = frozen_split(Path(args.checkpoint).parent / "split.json", sessions,
                                     val_frac=d_.get("val_frac", 0.2), seed=cfg.get("seed", 0), save=False)
    train_set, val_set = set(train_s), set(val_s)
    dyn = CarDynamics.fit([(r["raw_dir"], [s for s in r["_sessions"] if s in train_set]) for r in roots],
                          dt=0.22, stride=stride, speed_idx=spd_i, yaw_idx=yaw_i)
    d = args.distance
    planner = CEMPlannerAC(model, dyn, sm, ss, action_scale=ascale, horizon=d, n_iter=2,
                           history=2, prev_action_idx=prev_idx, score_chunk=96, device=args.device)
    ds = ACClipDataset(roots=[{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                               "sessions": [s for s in r["_sessions"] if s in val_set],
                               "domain_id": r.get("domain_id", 0)} for r in roots],
                       horizon=d + 1, frame_stride=stride, state_columns=cols,
                       action_scale=(1.0, 1.0), state_mean=None, max_gap=d_.get("max_gap"))
    grid = torch.linspace(-1, 1, args.grid, device=args.device)
    rng = np.random.default_rng(0); order = rng.permutation(len(ds))

    teas, a0s, contrasts, cemvar, cemlock = [], [], [], [], []
    seqs = torch.zeros(args.grid, d, 2, device=args.device)
    seqs[:, :, 0] = grid[:, None]
    n = 0
    for i in order:
        if n >= args.n_windows:
            break
        item = ds[int(i)]
        a_raw = item["actions"].float()
        tea = float(a_raw[:d, 0].mean()); thr = float(a_raw[:d, 1].mean())
        z = item["tokens"].to(args.device).float(); s0 = item["states"][0].to(args.device).float()
        dom = float(a_raw[0, -1]) if use_domain else None
        seqs[:, :, 1] = thr
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
            E = planner.score(z[:1], s0, z[d], seqs, domain=dom).float().cpu().numpy()
        a0 = float(grid[int(E.argmin())].cpu())
        teas.append(tea); a0s.append(a0)
        contrasts.append(float((E.max() - E.min()) / (E.min() + 1e-9)))
        if n < args.n_cem:                                   # H4: CEM sampling variance
            row_var, row_lock = {}, {}
            for S in (16, 32, 64, 128, 256):
                planner.n_samples = S; planner.n_elite = max(4, S // 8)
                outs = []
                for sd in range(args.seeds):
                    torch.manual_seed(sd)
                    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                        st, _ = planner.plan(z[:1], s0, z[d], domain=dom)
                    outs.append(float(st))
                row_var[S] = float(np.std(outs))
                row_lock[S] = float(np.mean([abs(o) > 0.7 for o in outs]))
            cemvar.append((tea, row_var)); cemlock.append((tea, row_lock))
        n += 1

    teas = np.array(teas); a0s = np.array(a0s); contrasts = np.array(contrasts)
    st_m = np.abs(teas) < 0.15; tn_m = ~st_m
    print(f"\n================ {n} window VAL (frozen), d={d} ================")
    print("── H2: ĐUÔI per-window (argmin vét cạn, không nhiễu sampling) ──")
    print(f"  ĐOẠN THẲNG (|tea|<0.15, n={st_m.sum()}): "
          f"%argmin ở BIÊN |a0|>0.7 = {100*np.mean(np.abs(a0s[st_m])>0.7):.0f}%  "
          f"| %energy PHẲNG contrast<0.1 = {100*np.mean(contrasts[st_m]<0.1):.0f}%")
    print(f"  CUA      (|tea|>0.15, n={tn_m.sum()}): "
          f"%argmin ở BIÊN = {100*np.mean(np.abs(a0s[tn_m])>0.7):.0f}%  "
          f"| %energy PHẲNG = {100*np.mean(contrasts[tn_m]<0.1):.0f}%")
    print(f"  contrast pct: p10 {np.percentile(contrasts,10):.3f}  p50 {np.percentile(contrasts,50):.3f}  "
          f"p90 {np.percentile(contrasts,90):.3f}")
    print("── H5: argminE bám teacher theo bucket |steer| (proxy recovery) ──")
    print(f"  {'bucket |tea|':>14} {'n':>4} {'sign-đúng':>10} {'median|a0-tea|':>15}")
    for lo, hi in [(0.0, 0.15), (0.15, 0.4), (0.4, 0.7), (0.7, 1.01)]:
        m = (np.abs(teas) >= lo) & (np.abs(teas) < hi)
        if m.sum() == 0: continue
        sgn = np.mean(np.sign(a0s[m]) == np.sign(teas[m])) if hi > 0.15 else float("nan")
        print(f"  {f'[{lo:.2f},{hi:.2f})':>14} {m.sum():>4} "
              f"{('—' if hi<=0.15 else f'{100*sgn:.0f}%'):>10} {np.median(np.abs(a0s[m]-teas[m])):>15.3f}")
    print(f"── H4: CEM sampling — phương sai argmin + %full-lock(thẳng) theo samples (seed={args.seeds}) ──")
    lock_st = [rl for (t, rl) in cemlock if abs(t) < 0.15]
    print(f"  {'samples':>8} {'med std argmin(all)':>20} {'%full-lock đoạn thẳng':>22}")
    for S in (16, 32, 64, 128, 256):
        v = np.median([rv[S] for (t, rv) in cemvar])
        lk = np.mean([rl[S] for rl in lock_st]) if lock_st else float("nan")
        print(f"  {S:>8} {v:>20.3f} {100*lk:>21.0f}%")


if __name__ == "__main__":
    main()
