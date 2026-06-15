#!/usr/bin/env python3
"""Energy-landscape probe — E(steer) quét [-1,1] trên window VAL thật (ban ngày).

Trả lời "đánh lái yếu / energy có tín hiệu lái không" TÁCH BẠCH khỏi chuyện
closed-loop (trễ, GPS, ánh sáng): với goal = patch map d bước phía trước, giữ
throttle = teacher, quét steer HẰNG theo horizon → mỗi window in argmin-steer vs
steer người lái + độ tương phản (E_max−E_min)/E_min. Landscape phẳng (contrast ~0)
= CEM không có gì để bám → lái yếu là tại model/goal; contrast rõ + argmin đúng
phía = model ổn, vấn đề nằm ở closed-loop.

    PYTHONPATH=src python scripts/probe_energy.py \
        --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt -d 4
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


def _strip_compile(sd):
    return {k.replace("_orig_mod.", "", 1): v for k, v in sd.items()}


def _spark(vals, width=41):
    """Đường năng lượng ASCII: thấp = '.', cao = '#' (8 mức)."""
    v = np.asarray(vals)
    v = (v - v.min()) / (v.max() - v.min() + 1e-12)
    chars = " .:-=+*#"
    return "".join(chars[int(x * (len(chars) - 1))] for x in v)


def plot_energy(ex_curves, teas, bests, contrast_med, sign_str, d, out):
    """2 panel: (trái) vài đường E(steer) chuẩn hoá; (phải) argmin-E vs teacher."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.6))
    for (g, E, tea, best) in ex_curves:
        en = (E - E.min()) / (E.max() - E.min() + 1e-12)
        color = "#d62728" if tea < 0 else "#1f77b4"
        axL.plot(g, en, "-", color=color, alpha=0.55, lw=1.4)
        axL.plot(g[int(np.argmin(en))], 0.0, "o", color=color, ms=7, mec="k", mew=0.5)
        axL.axvline(tea, color=color, ls=":", lw=1.0, alpha=0.5)
    axL.axvline(0, color="grey", lw=0.6)
    axL.set_xlabel("steer quét  (−1 = trái … +1 = phải)")
    axL.set_ylabel("năng lượng chuẩn hoá  ‖P − z_goal‖₁")
    axL.set_title(f"Energy landscape E(steer), d={d}\nđáy ● = argmin · đường chấm = teacher · "
                  "đỏ=cua trái, xanh=cua phải", fontsize=9)

    teas, bests = np.asarray(teas), np.asarray(bests)
    axR.fill([0, 1, 1, 0], [0, 0, 1, 1], color="#2ca02c", alpha=0.06)   # Q1 dấu đúng
    axR.fill([0, -1, -1, 0], [0, 0, -1, -1], color="#2ca02c", alpha=0.06)  # Q3 dấu đúng
    same = np.sign(teas) == np.sign(bests)
    axR.scatter(teas[same], bests[same], c="#2ca02c", s=30, edgecolor="k", linewidth=0.3, label="dấu đúng")
    axR.scatter(teas[~same], bests[~same], c="#d62728", s=34, marker="x", label="dấu sai")
    axR.plot([-1, 1], [-1, 1], color="grey", ls="--", lw=0.8)
    axR.axhline(0, color="grey", lw=0.6)
    axR.axvline(0, color="grey", lw=0.6)
    axR.set_xlim(-1.1, 1.1)
    axR.set_ylim(-1.1, 1.1)
    axR.set_aspect("equal")
    axR.set_xlabel("steer teacher (người lái)")
    axR.set_ylabel("argmin-E (model chọn)")
    axR.set_title(f"argmin-E vs teacher  ·  sign-đúng {sign_str}\nmedian contrast {contrast_med:.2f} "
                  "(landscape có đáy rõ, đúng phía cua)", fontsize=9)
    axR.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt")
    ap.add_argument("-d", "--distance", type=int, default=4, help="goal = d bước phía trước")
    ap.add_argument("--n-windows", type=int, default=24)
    ap.add_argument("--grid", type=int, default=21, help="số điểm quét steer trong [-1,1]")
    ap.add_argument("--with-throttle", action="store_true",
                    help="thêm quét trục GA (giữ lái = teacher) → in contrast_thr + ga model muốn (aggregate)")
    ap.add_argument("--grid-thr", type=int, default=19, help="số điểm quét throttle")
    ap.add_argument("--thr-min", type=float, default=-0.1)
    ap.add_argument("--thr-max", type=float, default=0.25)
    ap.add_argument("--turn-only", action="store_true",
                    help="chỉ lấy window người lái đang quẹo (|steer| > 0.15)")
    ap.add_argument("--frames-dir", default=None,
                    help="probe trên ẢNH TÙY Ý (vd indoor pre-check): mỗi jpg/png = 1 window "
                         "1-frame, goal = --goal-image, không cần teacher — đọc argminE + contrast. "
                         "Contrast ≪ tham chiếu park (0.39) = landscape phẳng = không đủ tín hiệu lái.")
    ap.add_argument("--goal-image", default=None, help="ảnh goal cho --frames-dir")
    ap.add_argument("--probe-throttle", type=float, default=0.05,
                    help="throttle hằng khi quét (mode --frames-dir)")
    ap.add_argument("--domain-id", type=float, default=1.0,
                    help="domain token cho mode --frames-dir (1=TowerPro)")
    ap.add_argument("--image-size", type=int, default=384)
    ap.add_argument("--history", type=int, default=2)
    ap.add_argument("--dt", type=float, default=0.22)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--plot", default=None, help="lưu hình energy-landscape (PNG) vào đường dẫn này")
    args = ap.parse_args()

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
    train_s, val_s, sinfo = frozen_split(split_path, sessions, val_frac=d_.get("val_frac", 0.2),
                                         seed=cfg.get("seed", 0), save=False)
    train_set, val_set = set(train_s), set(val_s)
    dyn = CarDynamics.fit([(r["raw_dir"], [s for s in r["_sessions"] if s in train_set]) for r in roots],
                          dt=args.dt, stride=stride, speed_idx=speed_idx, yaw_idx=yaw_idx)
    d = args.distance
    planner = CEMPlannerAC(model, dyn, state_mean, state_std, action_scale=ascale,
                           horizon=d, history=args.history, prev_action_idx=prev_idx,
                           device=args.device)

    if args.frames_dir:                      # ---- probe trên ảnh thật (indoor pre-check) ----
        if not args.goal_image:
            ap.error("--frames-dir cần --goal-image")
        import torch.nn.functional as F
        import PIL.Image as Image
        from jepa_wm.engine.encode import IMAGENET_MEAN, IMAGENET_STD, load_encoder
        enc = load_encoder(args.device)

        @torch.no_grad()
        def _tok(p):
            img = Image.open(p).convert("RGB").resize((args.image_size,) * 2, Image.BILINEAR)
            x = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
            x = ((x - IMAGENET_MEAN) / IMAGENET_STD).unsqueeze(0).unsqueeze(2).to(args.device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                t = enc(x)
            t = t.float()[0]
            return F.layer_norm(t, (t.size(-1),))           # per-token LN như ACClipDataset

        goal_t = _tok(args.goal_image)
        frames = sorted(Path(args.frames_dir).glob("*.jpg")) + sorted(Path(args.frames_dir).glob("*.png"))
        if not frames:
            ap.error(f"không có jpg/png trong {args.frames_dir}")
        s0 = torch.zeros(len(cols), device=args.device)     # không IMU — như app cũ (zero-fill)
        dom = float(args.domain_id) if use_domain else None
        grid = torch.linspace(-1.0, 1.0, args.grid)
        seqs = torch.zeros(args.grid, d, 2, device=args.device)
        seqs[:, :, 0] = grid[:, None].to(args.device)
        seqs[:, :, 1] = args.probe_throttle
        print(f"[probe] {args.frames_dir} -> goal {args.goal_image} | d={d} | "
              f"throttle={args.probe_throttle} | steer -1(trái) … +1(phải)")
        contrasts = []
        for p in frames:
            zf = _tok(p)
            with torch.no_grad():
                E = planner.score(zf.unsqueeze(0), s0, goal_t, seqs, domain=dom).cpu().numpy()
            k = int(np.argmin(E))
            c = float((E.max() - E.min()) / (E.min() + 1e-9))
            contrasts.append(c)
            print(f"{p.name:>28} argminE {float(grid[k]):+.2f} contrast {c:>6.3f}  |{_spark(E)}|")
        print(f"\n[probe] median contrast = {np.median(contrasts):.3f} "
              f"(tham chiếu park ban ngày ≈ 0.39; ≪0.1 = phẳng → indoor không đủ tín hiệu)")
        return

    ds = ACClipDataset(roots=[{"patch_dir": r["patch_dir"], "raw_dir": r["raw_dir"],
                               "sessions": [s for s in r["_sessions"] if s in val_set],
                               "domain_id": r.get("domain_id", 0)} for r in roots],
                       horizon=d + 1, frame_stride=stride, state_columns=cols,
                       action_scale=(1.0, 1.0), state_mean=None, max_gap=d_.get("max_gap"))

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(ds))
    grid = torch.linspace(-1.0, 1.0, args.grid)
    print(f"[probe] {args.checkpoint} | d={d} ({d * stride * 0.11:.1f}s) | {sinfo and 'FROZEN split'} "
          f"| grid {args.grid} điểm steer, throttle = teacher")
    print(f"{'win':>5} {'tea_steer':>9} {'argminE':>8} {'contrast':>9}  E(steer) -1 … +1   (^ = teacher)")

    grid_thr = torch.linspace(args.thr_min, args.thr_max, args.grid_thr)
    derr, signs, contrasts, shown = [], [], [], 0
    contrasts_thr, model_thr = [], []
    teas_all, bests_all, ex_curves = [], [], []
    grid_np = grid.numpy()
    for i in order:
        item = ds[int(i)]
        a_raw = item["actions"].float()
        tea = float(a_raw[:d, 0].mean())
        if args.turn_only and abs(tea) < 0.15:
            continue
        z = item["tokens"].to(args.device).float()
        s0 = item["states"][0].to(args.device).float()
        dom = float(a_raw[0, -1]) if use_domain else None
        thr = float(a_raw[:d, 1].mean())
        seqs = torch.zeros(args.grid, d, 2, device=args.device)
        seqs[:, :, 0] = grid[:, None].to(args.device)
        seqs[:, :, 1] = thr
        with torch.no_grad():
            E = planner.score(z[:1], s0, z[d], seqs, domain=dom).cpu().numpy()
        k = int(np.argmin(E))
        best = float(grid[k])
        contrast = float((E.max() - E.min()) / (E.min() + 1e-9))
        if args.with_throttle:                       # quét GA, giữ lái = teacher
            seqs_t = torch.zeros(args.grid_thr, d, 2, device=args.device)
            seqs_t[:, :, 0] = tea
            seqs_t[:, :, 1] = grid_thr[:, None].to(args.device)
            with torch.no_grad():
                E_t = planner.score(z[:1], s0, z[d], seqs_t, domain=dom).cpu().numpy()
            contrasts_thr.append(float((E_t.max() - E_t.min()) / (E_t.min() + 1e-9)))
            model_thr.append(float(grid_thr[int(np.argmin(E_t))]))
        derr.append(abs(best - tea))
        if abs(tea) > 0.15:
            signs.append(np.sign(best) == np.sign(tea))
        contrasts.append(contrast)
        teas_all.append(tea)
        bests_all.append(best)
        if args.plot and len(ex_curves) < 7 and abs(tea) > 0.15:
            ex_curves.append((grid_np, np.asarray(E), tea, best))
        if shown < 8:
            curve = _spark(E)
            tpos = int(round((tea + 1) / 2 * (args.grid - 1)))
            mark = " " * tpos + "^"
            print(f"{int(i):>5} {tea:>+9.2f} {best:>+8.2f} {contrast:>9.3f}  |{curve}|")
            print(f"{'':>34}  |{mark:<{args.grid}}|")
            shown += 1
        if len(derr) >= args.n_windows:
            break

    print(f"\n[probe] {len(derr)} window: median |argminE − teacher| = {np.median(derr):.3f}"
          f" | sign-đúng khi quẹo (|tea|>0.15): {int(np.sum(signs))}/{len(signs)}"
          f" | median contrast = {np.median(contrasts):.3f}")
    if args.with_throttle and contrasts_thr:
        mt = np.asarray(model_thr)
        print(f"[probe-throttle] median contrast_thr = {np.median(contrasts_thr):.3f}"
              f" | ga model muốn: median {np.median(mt):+.3f} (mean {mt.mean():+.3f})"
              f" | % muốn TIẾN (>0): {100 * np.mean(mt > 0):.0f}%")

    if args.plot:
        plot_energy(ex_curves, teas_all, bests_all, float(np.median(contrasts)),
                    f"{int(np.sum(signs))}/{len(signs)}", d, args.plot)


if __name__ == "__main__":
    main()
