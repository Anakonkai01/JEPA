import csv, math
from pathlib import Path
import numpy as np

RAW = Path("data/raw_towerpro")
MLAT = 110540.0
def mlon(lat0): return 111320.0 * math.cos(math.radians(lat0))

scatters, drifts = [], []
for sess in sorted(RAW.glob("session_*")):
    gp, tp = sess/"gps.csv", sess/"telemetry.csv"
    if not gp.exists() or not tp.exists(): continue
    G = list(csv.DictReader(open(gp)))
    T = list(csv.DictReader(open(tp)))
    try:
        gt = np.array([float(r["t_ms"]) for r in G]); gla = np.array([float(r["lat"]) for r in G])
        glo = np.array([float(r["lon"]) for r in G]); gsp = np.array([float(r.get("speed",0) or 0) for r in G])
        tt = np.array([float(r["t_ms"]) for r in T]); tth = np.array([float(r["throttle"]) for r in T])
    except (ValueError, KeyError): continue
    ok = (gla != 0) & (glo != 0)
    gt, gla, glo, gsp = gt[ok], gla[ok], glo[ok], gsp[ok]
    if len(gt) < 20: continue
    lat0 = gla.mean()
    x = (glo - glo.mean()) * mlon(lat0); y = (gla - gla.mean()) * MLAT
    # stationary = commanded |throttle|<0.01 (interp to gps times) and doppler<0.05
    th_at = np.interp(gt, tt, np.abs(tth))
    still = (th_at < 0.01) & (gsp < 0.05)
    # contiguous runs >= 5s
    i = 0
    while i < len(gt):
        if not still[i]: i += 1; continue
        j = i
        while j + 1 < len(gt) and still[j + 1]: j += 1
        if gt[j] - gt[i] >= 5000:
            xs, ys = x[i:j+1], y[i:j+1]
            scatters.append(float(np.hypot(xs - xs.mean(), ys - ys.mean()).max()))
            # drift over consecutive 3s sub-spans (relative error at stuck_s scale)
            t0 = gt[i]
            while t0 + 3000 <= gt[j]:
                a = np.searchsorted(gt, t0); b = np.searchsorted(gt, t0 + 3000)
                b = min(b, j)
                drifts.append(float(np.hypot(x[b]-x[a], y[b]-y[a])))
                t0 += 3000
        i = j + 1
sc, dr = np.array(scatters), np.array(drifts)
print(f"stationary segments(>=5s): {len(sc)} | scatter max-from-centroid: "
      f"median {np.median(sc):.2f}m p90 {np.percentile(sc,90):.2f}m max {sc.max():.2f}m")
print(f"3s-window NET drift while stationary: n={len(dr)} median {np.median(dr):.2f}m "
      f"p90 {np.percentile(dr,90):.2f}m p99 {np.percentile(dr,99):.2f}m max {dr.max():.2f}m")
print(f"  -> false 'moved>0.6m' while truly still: {(dr>0.6).mean()*100:.1f}%")
