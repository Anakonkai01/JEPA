#!/usr/bin/env python3
"""Dataset statistics + charts for the report.

Scans data/raw_kds + data/raw_towerpro (the two real servo domains; raw_mixed is just
symlinks to their union). Computes per-session frame counts / durations, total minutes &
hours, and steering / throttle / speed distributions, standstill fraction, turning events,
and time-of-day coverage. Writes PNG charts to docs/report/figures/ and a JSON/table dump.

    PYTHONPATH=src python scripts/dataset_stats.py
"""
from __future__ import annotations
import csv, json
from pathlib import Path
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from jepa_wm.data.state import load_state

DOMAINS = {"KDS": "data/raw_kds", "TowerPro": "data/raw_towerpro"}
FIG = Path("docs/report/figures"); FIG.mkdir(parents=True, exist_ok=True)
STILL = 0.06          # m/s below this = standstill (CEM deadzone)
TURN = 0.15           # |steer| above this = turning


def read_actions(sdir):
    with open(Path(sdir) / "actions_synced.csv") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r["t_scene_ms"]) for r in rows])
    st = np.array([float(r["steering"]) for r in rows])
    th = np.array([float(r["throttle"]) for r in rows])
    return t, st, th


def turning_events(steer):
    """count contiguous runs of |steer|>TURN."""
    on = np.abs(steer) > TURN
    return int(np.sum(on[1:] & ~on[:-1]) + (1 if len(on) and on[0] else 0))


def main():
    per_session = []          # dict per session
    agg = defaultdict(lambda: {"steer": [], "throt": [], "speed": []})
    series = {}               # name -> (t, steer, throt) for the time-series example chart
    hour_frames = defaultdict(int)
    for dom, root in DOMAINS.items():
        for sdir in sorted(Path(root).glob("session_*")):
            try:
                t, st, th = read_actions(sdir)
            except Exception:
                continue
            if len(t) < 5:
                continue
            dur = (t.max() - t.min()) / 1000.0
            fps = (len(t) - 1) / dur if dur > 0 else 0
            try:
                sp, _ = load_state(sdir, columns=("speed",)); sp = sp[:, 0]
            except Exception:
                sp = np.zeros(len(t))
            n = min(len(sp), len(st))
            still = float(np.mean(sp[:n] < STILL))
            # hour of day from session name session_YYYYMMDD_HHMMSS
            try:
                hh = int(sdir.name.split("_")[2][:2]); hour_frames[hh] += len(t)
            except Exception:
                pass
            per_session.append({
                "session": sdir.name, "domain": dom, "frames": len(t),
                "dur_s": round(dur, 1), "fps": round(fps, 2),
                "steer_std": round(float(st.std()), 4), "throt_mean": round(float(th.mean()), 4),
                "throt_std": round(float(th.std()), 4), "speed_mean": round(float(sp[:n].mean()), 3),
                "still_frac": round(still, 3), "turn_events": turning_events(st),
            })
            # subsample for global histograms (keep memory small)
            agg[dom]["steer"].append(st); agg[dom]["throt"].append(th); agg[dom]["speed"].append(sp[:n])
            series[sdir.name] = (t, st, th)

    for d in agg:
        for k in agg[d]:
            agg[d][k] = np.concatenate(agg[d][k]) if agg[d][k] else np.array([])

    # ---- totals -------------------------------------------------------------------------
    def totals(rows):
        n_s = len(rows); n_f = sum(r["frames"] for r in rows); secs = sum(r["dur_s"] for r in rows)
        return n_s, n_f, secs
    summ = {"per_domain": {}, "figures": []}
    print(f"{'domain':10s} {'sess':>5s} {'frames':>8s} {'minutes':>8s} {'hours':>6s} {'avg_fps':>8s}")
    grand = [0, 0, 0.0]
    for dom in list(DOMAINS) + ["ALL"]:
        rows = [r for r in per_session if (dom == "ALL" or r["domain"] == dom)]
        n_s, n_f, secs = totals(rows)
        afps = np.mean([r["fps"] for r in rows]) if rows else 0
        print(f"{dom:10s} {n_s:>5d} {n_f:>8d} {secs/60:>8.1f} {secs/3600:>6.2f} {afps:>8.2f}")
        summ["per_domain"][dom] = {"sessions": n_s, "frames": n_f, "minutes": round(secs/60, 1),
                                   "hours": round(secs/3600, 2), "avg_fps": round(float(afps), 2)}
    all_steer = np.concatenate([agg[d]["steer"] for d in agg if len(agg[d]["steer"])])
    all_throt = np.concatenate([agg[d]["throt"] for d in agg if len(agg[d]["throt"])])
    all_speed = np.concatenate([agg[d]["speed"] for d in agg if len(agg[d]["speed"])])
    summ["overall"] = {
        "frames": int(len(all_steer)),
        "standstill_frac": round(float(np.mean(all_speed < STILL)), 3),
        "steer_zero_frac": round(float(np.mean(np.abs(all_steer) < TURN)), 3),
        "turn_events_total": int(sum(r["turn_events"] for r in per_session)),
        "throttle_median": round(float(np.median(all_throt)), 4),
        "speed_median_mps": round(float(np.median(all_speed)), 3),
        "speed_p90_mps": round(float(np.percentile(all_speed, 90)), 3),
    }
    print("\noverall:", json.dumps(summ["overall"]))

    # ---- charts -------------------------------------------------------------------------
    C = {"KDS": "#d9534f", "TowerPro": "#0275d8"}

    def hist(col, title, fname, xlabel, rng):
        plt.figure(figsize=(6, 3.4))
        for d in DOMAINS:
            v = agg[d][col]
            if len(v):
                plt.hist(v, bins=60, range=rng, alpha=0.6, label=f"{d} (n={len(v):,})", color=C[d], density=True)
        plt.xlabel(xlabel); plt.ylabel("density"); plt.title(title); plt.legend(fontsize=8)
        plt.tight_layout(); p = FIG / fname; plt.savefig(p, dpi=130); plt.close()
        summ["figures"].append(str(p)); print("wrote", p)

    hist("steer", "Steering distribution", "fig_data_steer_hist.png", "steer [-1,1]", (-1, 1))
    hist("throt", "Throttle distribution — KDS ~constant vs TowerPro varied", "fig_data_throttle_hist.png", "throttle", (-0.2, 0.3))
    hist("speed", "Speed distribution (GPS)", "fig_data_speed_hist.png", "speed (m/s)", (0, max(2.0, float(np.percentile(all_speed, 99)))))

    # per-session duration sorted, colored by domain
    plt.figure(figsize=(7, 3.4))
    rows = sorted(per_session, key=lambda r: r["dur_s"])
    plt.bar(range(len(rows)), [r["dur_s"] for r in rows],
            color=[C[r["domain"]] for r in rows], width=1.0)
    plt.xlabel("session (sorted by length)"); plt.ylabel("duration (s)")
    plt.title(f"Length of {len(rows)} sessions (red=KDS, blue=TowerPro)")
    plt.tight_layout(); p = FIG / "fig_data_sessions.png"; plt.savefig(p, dpi=130); plt.close()
    summ["figures"].append(str(p)); print("wrote", p)

    # time-of-day coverage
    plt.figure(figsize=(6, 3.0))
    hs = sorted(hour_frames)
    plt.bar(hs, [hour_frames[h] for h in hs], color="#5cb85c")
    plt.xlabel("hour of day"); plt.ylabel("#frames"); plt.title("Data-collection time-of-day coverage")
    plt.tight_layout(); p = FIG / "fig_data_timeofday.png"; plt.savefig(p, dpi=130); plt.close()
    summ["figures"].append(str(p)); print("wrote", p)

    # steering+throttle TIME SERIES of one busy session — shows the human constantly
    # correcting left/right (i.e. corrective / recovery-like driving IS present in the data).
    ex_name = max(per_session, key=lambda r: r["turn_events"])["session"]
    t, st, th = series[ex_name]
    tt = (t - t.min()) / 1000.0
    m = tt <= min(tt.max(), 90.0)                      # first ~90 s for readability
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.axhline(0, color="grey", lw=0.6)
    ax.plot(tt[m], st[m], color="#6a3d9a", lw=1.4, label="steering (steer)")
    ax.plot(tt[m], th[m], color="#ff7f0e", lw=1.0, alpha=0.8, label="throttle")
    ax.fill_between(tt[m], -1, 1, where=np.abs(st[m]) > TURN, color="#6a3d9a", alpha=0.06)
    ax.set_xlabel("time (s)"); ax.set_ylabel("normalized command [-1,1]")
    ax.set_ylim(-1.05, 1.05)
    ax.set_title(f"Manual steering oscillates both ways continuously ({ex_name}, {int(m.sum())} frames)\n"
                 "→ data CONTAINS corrective / recovery behavior (not straight-line driving)",
                 fontsize=9)
    ax.legend(fontsize=8, loc="upper right")
    plt.tight_layout(); p = FIG / "fig_data_steer_timeseries.png"; plt.savefig(p, dpi=140); plt.close()
    summ["figures"].append(str(p)); print("wrote", p)

    # 2-D density steer x throttle (joint action coverage)
    plt.figure(figsize=(5.4, 4.2))
    h = plt.hist2d(all_steer, all_throt, bins=[60, 50], range=[[-1, 1], [-0.2, 0.3]],
                   cmap="magma", cmin=1)
    plt.colorbar(h[3], label="#frames")
    plt.xlabel("steering (steer)"); plt.ylabel("throttle")
    plt.title("Joint steering × throttle density (whole dataset)")
    plt.tight_layout(); p = FIG / "fig_data_steer_throttle_2d.png"; plt.savefig(p, dpi=140); plt.close()
    summ["figures"].append(str(p)); print("wrote", p)
    summ["example_session"] = ex_name

    summ["per_session"] = per_session
    Path("docs/report/figures/dataset_stats.json").write_text(json.dumps(summ, indent=1))
    print("\nwrote docs/report/figures/dataset_stats.json")


if __name__ == "__main__":
    main()
