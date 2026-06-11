#!/usr/bin/env python3
"""Replay recovery-v2 stuck detector (inference_loop.py logic) over human-driven sessions.

Per tick (1.36s = measured closed-loop period):
  car_xy   = latest GPS fix <= tick time (what the phone meta gives the PC)
  throt    = commanded throttle from telemetry.csv nearest the tick
  pos_hist = (t, xy) window of stuck_s seconds, exactly like inference_loop
  trigger  = throt > 0.03 and span >= 0.7*stuck_s and net_disp < stuck_m

Label each trigger with what the car ACTUALLY did next (GPS over next 3s):
  next3 > 1.0 m  -> FALSE positive (car was moving / kept moving; would have been
                    reversed by recovery for no reason)
  next3 < 0.5 m  -> plausibly TRUE (really stuck)
  else           -> ambiguous
"""
import csv, math, sys
from pathlib import Path
import numpy as np

RAW = Path("data/raw_towerpro")
MLAT = 110540.0

def m_per_deg_lon(lat0): return 111320.0 * math.cos(math.radians(lat0))

def read_gps(p):
    t, la, lo, sp = [], [], [], []
    if not p.exists(): return None
    for r in csv.DictReader(open(p)):
        try:
            a, b = float(r["lat"]), float(r["lon"])
            if a == 0 or b == 0: continue
            t.append(float(r["t_ms"])); la.append(a); lo.append(b)
            sp.append(float(r.get("speed", 0) or 0))
        except (ValueError, KeyError): continue
    if len(t) < 10: return None
    return np.array(t), np.array(la), np.array(lo), np.array(sp)

def read_telem(p):
    t, th = [], []
    if not p.exists(): return None
    for r in csv.DictReader(open(p)):
        try:
            t.append(float(r["t_ms"])); th.append(float(r["throttle"]))
        except (ValueError, KeyError): continue
    if len(t) < 10: return None
    return np.array(t), np.array(th)

def run(stuck_s, stuck_m, tick, label):
    tot_trig = tot_false = tot_true = tot_amb = 0
    tot_time = 0.0
    sessions = sorted(RAW.glob("session_*"))
    fix_dts, fix_same = [], 0
    n_fix = 0
    n_sess = 0
    for sess in sessions:
        g = read_gps(sess / "gps.csv")
        tm = read_telem(sess / "telemetry.csv")
        if g is None or tm is None: continue
        gt, gla, glo, gsp = g
        tt, tth = tm
        lat0 = float(gla.mean())
        x = (glo - glo.mean()) * m_per_deg_lon(lat0)
        y = (gla - gla.mean()) * MLAT
        # GPS fix cadence stats
        d = np.diff(gt) / 1000.0
        fix_dts.extend(d.tolist())
        same = (np.diff(x) == 0) & (np.diff(y) == 0)
        fix_same += int(same.sum()); n_fix += len(d)
        # session must overlap telemetry
        t0, t1 = max(gt[0], tt[0]), min(gt[-1], tt[-1])
        if t1 - t0 < 10000: continue
        n_sess += 1
        tot_time += (t1 - t0) / 1000.0
        pos_hist = []
        tk = t0
        skip_until = -1
        while tk < t1:
            # latest fix <= tk (staleness as in real meta)
            i = np.searchsorted(gt, tk, side="right") - 1
            xy = np.array([x[i], y[i]])
            # commanded throttle nearest tick
            j = np.searchsorted(tt, tk); j = min(j, len(tt) - 1)
            throt = tth[j]
            now = tk / 1000.0
            pos_hist.append((now, xy))
            while pos_hist and now - pos_hist[0][0] > stuck_s:
                pos_hist.pop(0)
            moved = float(np.linalg.norm(xy - pos_hist[0][1]))
            span = now - pos_hist[0][0]
            if tk > skip_until and throt > 0.03 and span >= stuck_s * 0.7 and moved < stuck_m:
                tot_trig += 1
                # ground truth: net displacement over the NEXT 3s
                i2 = np.searchsorted(gt, tk + 3000, side="right") - 1
                nxt = float(np.hypot(x[i2] - xy[0], y[i2] - xy[1]))
                if nxt > 1.0: tot_false += 1
                elif nxt < 0.5: tot_true += 1
                else: tot_amb += 1
                pos_hist.clear()          # re-arm like the real code post-recovery
                skip_until = tk + 2000    # the real car would spend ~2s reversing
            tk += tick * 1000.0
    mins = tot_time / 60.0
    print(f"[{label}] sessions={n_sess} drive-time={mins:.0f}min "
          f"triggers={tot_trig} ({tot_trig/mins:.2f}/min) | "
          f"FALSE(next3>1m)={tot_false} TRUE(next3<0.5m)={tot_true} ambiguous={tot_amb}")
    if n_fix:
        dts = np.array(fix_dts)
        print(f"    gps fixes: median dt={np.median(dts):.2f}s p90={np.percentile(dts,90):.2f}s "
              f"identical-consecutive-fix={100*fix_same/n_fix:.1f}%")

run(stuck_s=2.0, stuck_m=0.6, tick=1.36, label="default --stuck-s 2.0")
run(stuck_s=3.0, stuck_m=0.6, tick=1.36, label="recommended --stuck-s 3.0")
run(stuck_s=3.0, stuck_m=0.6, tick=0.7,  label="stuck-s 3.0, tick 0.7s (faster loop)")

# ---- candidate fix: also require NO movement in the trailing tick ----
def run_fixed(stuck_s, stuck_m, tick, recent_m, label):
    tot_trig = tot_false = tot_true = tot_amb = 0
    tot_time = 0.0
    for sess in sorted(RAW.glob("session_*")):
        g = read_gps(sess / "gps.csv"); tm = read_telem(sess / "telemetry.csv")
        if g is None or tm is None: continue
        gt, gla, glo, gsp = g; tt, tth = tm
        lat0 = float(gla.mean())
        x = (glo - glo.mean()) * m_per_deg_lon(lat0); y = (gla - gla.mean()) * MLAT
        t0, t1 = max(gt[0], tt[0]), min(gt[-1], tt[-1])
        if t1 - t0 < 10000: continue
        tot_time += (t1 - t0) / 1000.0
        pos_hist = []; tk = t0; skip_until = -1
        while tk < t1:
            i = np.searchsorted(gt, tk, side="right") - 1
            xy = np.array([x[i], y[i]])
            j = min(np.searchsorted(tt, tk), len(tt) - 1); throt = tth[j]
            now = tk / 1000.0
            pos_hist.append((now, xy))
            while pos_hist and now - pos_hist[0][0] > stuck_s:
                pos_hist.pop(0)
            moved = float(np.linalg.norm(xy - pos_hist[0][1]))
            span = now - pos_hist[0][0]
            recent = float(np.linalg.norm(xy - pos_hist[-2][1])) if len(pos_hist) >= 2 else 99.0
            if (tk > skip_until and throt > 0.03 and span >= stuck_s * 0.7
                    and moved < stuck_m and recent < recent_m):
                tot_trig += 1
                i2 = np.searchsorted(gt, tk + 3000, side="right") - 1
                nxt = float(np.hypot(x[i2] - xy[0], y[i2] - xy[1]))
                if nxt > 1.0: tot_false += 1
                elif nxt < 0.5: tot_true += 1
                else: tot_amb += 1
                pos_hist.clear(); skip_until = tk + 2000
            tk += tick * 1000.0
    mins = tot_time / 60.0
    print(f"[{label}] triggers={tot_trig} ({tot_trig/mins:.2f}/min) | "
          f"FALSE={tot_false} TRUE={tot_true} ambiguous={tot_amb}")

run_fixed(3.0, 0.6, 1.36, 0.25, "FIX recent<0.25m, stuck-s 3.0")
run_fixed(3.0, 0.6, 1.36, 0.20, "FIX recent<0.20m, stuck-s 3.0")

# ---- fix v3: forward command must be held the WHOLE window + no recent movement ----
def run_v3(stuck_s, stuck_m, tick, recent_m, label):
    tot_trig = tot_false = tot_true = tot_amb = 0
    tot_time = 0.0
    for sess in sorted(RAW.glob("session_*")):
        g = read_gps(sess / "gps.csv"); tm = read_telem(sess / "telemetry.csv")
        if g is None or tm is None: continue
        gt, gla, glo, gsp = g; tt, tth = tm
        lat0 = float(gla.mean())
        x = (glo - glo.mean()) * m_per_deg_lon(lat0); y = (gla - gla.mean()) * MLAT
        t0, t1 = max(gt[0], tt[0]), min(gt[-1], tt[-1])
        if t1 - t0 < 10000: continue
        tot_time += (t1 - t0) / 1000.0
        hist = []; tk = t0; skip_until = -1   # (t, xy, throt_cmd)
        while tk < t1:
            i = np.searchsorted(gt, tk, side="right") - 1
            xy = np.array([x[i], y[i]])
            j = min(np.searchsorted(tt, tk), len(tt) - 1); throt = tth[j]
            now = tk / 1000.0
            hist.append((now, xy, throt))
            while hist and now - hist[0][0] > stuck_s:
                hist.pop(0)
            moved = float(np.linalg.norm(xy - hist[0][1]))
            span = now - hist[0][0]
            recent = float(np.linalg.norm(xy - hist[-2][1])) if len(hist) >= 2 else 99.0
            pushing_all = all(h[2] > 0.03 for h in hist)
            if (tk > skip_until and pushing_all and span >= stuck_s * 0.7
                    and moved < stuck_m and recent < recent_m):
                tot_trig += 1
                i2 = np.searchsorted(gt, tk + 3000, side="right") - 1
                nxt = float(np.hypot(x[i2] - xy[0], y[i2] - xy[1]))
                if nxt > 1.0: tot_false += 1
                elif nxt < 0.5: tot_true += 1
                else: tot_amb += 1
                hist.clear(); skip_until = tk + 2000
            tk += tick * 1000.0
    mins = tot_time / 60.0
    print(f"[{label}] triggers={tot_trig} ({tot_trig/mins:.2f}/min) | "
          f"FALSE={tot_false} TRUE={tot_true} ambiguous={tot_amb}")

run_v3(3.0, 0.6, 1.36, 0.25, "FIXv3 push-all-window + recent<0.25")
run_v3(3.0, 0.6, 1.36, 99.0, "FIXv3 push-all-window only")

# ---- EXACT semantics as implemented in inference_loop.py (v2.1) ----
def run_impl(stuck_s, stuck_m, tick, recent_m, label):
    tot_trig = tot_false = tot_true = tot_amb = 0
    tot_time = 0.0
    for sess in sorted(RAW.glob("session_*")):
        g = read_gps(sess / "gps.csv"); tm = read_telem(sess / "telemetry.csv")
        if g is None or tm is None: continue
        gt, gla, glo, gsp = g; tt, tth = tm
        lat0 = float(gla.mean())
        x = (glo - glo.mean()) * m_per_deg_lon(lat0); y = (gla - gla.mean()) * MLAT
        t0, t1 = max(gt[0], tt[0]), min(gt[-1], tt[-1])
        if t1 - t0 < 10000: continue
        tot_time += (t1 - t0) / 1000.0
        hist = []; tk = t0; skip_until = -1
        while tk < t1:
            i = np.searchsorted(gt, tk, side="right") - 1
            xy = np.array([x[i], y[i]])
            j = min(np.searchsorted(tt, tk), len(tt) - 1); throt = tth[j]
            now = tk / 1000.0
            hist.append((now, xy, throt > 0.03))
            while len(hist) > 2 and now - hist[1][0] > stuck_s:
                hist.pop(0)
            moved = float(np.linalg.norm(xy - hist[0][1]))
            span = now - hist[0][0]
            recent = float(np.linalg.norm(xy - hist[-2][1])) if len(hist) >= 2 else 9.9
            pushing_all = all(h[2] for h in hist)
            if (tk > skip_until and pushing_all and span >= stuck_s * 0.7
                    and moved < stuck_m and recent < recent_m):
                tot_trig += 1
                i2 = np.searchsorted(gt, tk + 3000, side="right") - 1
                nxt = float(np.hypot(x[i2] - xy[0], y[i2] - xy[1]))
                if nxt > 1.0: tot_false += 1
                elif nxt < 0.5: tot_true += 1
                else: tot_amb += 1
                hist.clear(); skip_until = tk + 2000
            tk += tick * 1000.0
    mins = tot_time / 60.0
    print(f"[{label}] triggers={tot_trig} ({tot_trig/mins:.2f}/min) | "
          f"FALSE={tot_false} TRUE={tot_true} ambiguous={tot_amb}")

run_impl(2.0, 0.6, 1.36, 0.25, "IMPL v2.1 stuck-s 2.0 (default)")
run_impl(3.0, 0.6, 1.36, 0.25, "IMPL v2.1 stuck-s 3.0")
