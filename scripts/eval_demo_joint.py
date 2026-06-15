#!/usr/bin/env python3
"""Aggregate the JOINT (steer×throttle) open-loop demo results across sessions.

Reads data/demo/*/demo.json that have the joint 2-D landscape (frames carry E2 + model picks
both axes together). Reports, over all turning frames pooled:
  - sign-turn accuracy (model steer sign == human steer sign)
  - |Δsteer| median (model vs human)
  - throttle behaviour: % model wants forward (>0), median model throttle vs human, corr
  - contrast (joint 2-D landscape depth)

    PYTHONPATH=src python scripts/eval_demo_joint.py
"""
import json, glob, os
import numpy as np

TURN = 0.15
rows, all_ds, all_thr_m, all_thr_h, all_con, all_signok = [], [], [], [], [], []
n_turn_tot = 0
sessions = []
for p in sorted(glob.glob("data/demo/*/demo.json")):
    d = json.load(open(p))
    F = d["frames"]
    if not F or "E2" not in F[0]:
        continue                      # skip old 1-D format
    s = os.path.basename(os.path.dirname(p))
    sessions.append(s)
    ms = np.array([f["model_steer"] for f in F]); hs = np.array([f["human_steer"] for f in F])
    mt = np.array([f["model_throttle"] for f in F]); ht = np.array([f["human_throttle"] for f in F])
    con = np.array([f["contrast"] for f in F])
    turn = np.abs(hs) > TURN
    signok = np.sign(ms[turn]) == np.sign(hs[turn])
    rows.append((s, d.get("is_val"), len(F), int(turn.sum()),
                 round(float(signok.mean()), 3) if turn.sum() else None,
                 round(float(np.median(np.abs(ms[turn] - hs[turn]))), 3) if turn.sum() else None,
                 round(float((mt > 0).mean()), 3), round(float(np.median(mt)), 3),
                 round(float(np.median(con)), 3)))
    all_ds += list(np.abs(ms[turn] - hs[turn])); all_signok += list(signok)
    all_thr_m += list(mt); all_thr_h += list(ht); all_con += list(con)
    n_turn_tot += int(turn.sum())

print(f"JOINT demo sessions: {len(sessions)}")
print(f"{'session':32} {'val':>5} {'n':>5} {'nturn':>6} {'sign':>6} {'|Δs|':>5} {'%ga>0':>6} {'ga_med':>7} {'con':>5}")
for r in rows:
    print(f"{r[0]:32} {str(r[1]):>5} {r[2]:>5} {r[3]:>6} {str(r[4]):>6} {str(r[5]):>5} {str(r[6]):>6} {str(r[7]):>7} {str(r[8]):>5}")

if all_signok:
    print("\n=== POOLED (mọi turning frame của các session joint) ===")
    print(f"  sign-turn:        {int(np.sum(all_signok))}/{len(all_signok)} = {np.mean(all_signok):.3f}")
    print(f"  |Δsteer| median:  {np.median(all_ds):.3f}")
    print(f"  ga model >0:      {np.mean(np.array(all_thr_m)>0):.3f}  (model muốn tiến)")
    print(f"  ga model median:  {np.median(all_thr_m):+.3f}  |  ga người median: {np.median(all_thr_h):+.3f}")
    print(f"  contrast (joint): median {np.median(all_con):.3f}")
