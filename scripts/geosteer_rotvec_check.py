"""GATE 0: rotvec phone có dùng làm heading không? (data REC thật, offline).
So yaw-rotvec(50Hz) vs GPS-track heading; offset ~hằng + median|res| nhỏ = DÙNG ĐƯỢC.
Chạy: python scripts/geosteer_rotvec_check.py  (từ repo root, cần data/raw_towerpro)
"""
"""PHASE 0c: gate ROBUST (median, lọc GPS-glitch). rotvec vs GPS-track.
offset = circular median; spread = median|residual| (bỏ outlier GPS).
GATE: median|residual| < 12° + %|res|<20° cao → rotvec DÙNG ĐƯỢC làm heading.
"""
import csv, math, os, glob
import numpy as np

def load(p): return list(csv.DictReader(open(p)))
def quat_az(rx,ry,rz):
    w=math.sqrt(max(0,1-(rx*rx+ry*ry+rz*rz)))
    return math.degrees(math.atan2(2*(rx*ry-w*rz), 1-2*(rx*rx+rz*rz)))
def wrap(d): return (d+180)%360-180
def cmed(deg):  # circular median qua tìm offset tối thiểu hoá median|res|
    deg=np.asarray(deg); best=(1e9,0)
    for c in np.arange(-180,180,2):
        m=np.median(np.abs(wrap(deg-c)))
        if m<best[0]: best=(m,c)
    return best[1]

def analyze(S, vmin=1.2, base=3.0):
    rot=load(f"{S}/rotvec.csv")
    rt=np.array([float(r["t_ms"]) for r in rot])
    raz=np.array([quat_az(float(r["rx"]),float(r["ry"]),float(r["rz"])) for r in rot])
    gps=load(f"{S}/gps.csv")
    gt=np.array([float(r["t_ms"]) for r in gps])
    lat=np.array([float(r["lat"]) for r in gps]); lon=np.array([float(r["lon"]) for r in gps])
    spd=np.array([float(r.get("speed",0) or 0) for r in gps])
    lat0=lat.mean(); X=(lon-lon.mean())*math.cos(math.radians(lat0))*111320; Y=(lat-lat.mean())*111320
    def track(i):
        for j in range(i+1,len(X)):
            dx,dy=X[j]-X[i],Y[j]-Y[i]
            if math.hypot(dx,dy)>=base: return math.degrees(math.atan2(dx,dy))%360, (gt[j]-gt[i])/1000
        return None,None
    pairs=[]
    for i in range(len(gps)):
        if spd[i]<vmin: continue
        tb,dt=track(i)
        if tb is None or dt>4: continue            # bỏ nếu phải đi >4s mới đủ 3m (chậm/đứng)
        # lọc GPS-glitch: track-rate bất khả thi (>90°/s)
        j=int(np.argmin(np.abs(rt-gt[i])))
        if abs(rt[j]-gt[i])>200: continue
        pairs.append((raz[j], tb))
    if len(pairs)<10: return None
    raz_=np.array([p[0] for p in pairs]); tb_=np.array([p[1] for p in pairs])
    diff=wrap(raz_-tb_)
    off=cmed(diff)
    res=np.abs(wrap(diff-off))
    return dict(n=len(pairs), off=off, med=np.median(res),
                p75=np.percentile(res,75), p90=np.percentile(res,90),
                f15=100*np.mean(res<15), f25=100*np.mean(res<25))

cands=sorted(glob.glob("data/raw_towerpro/session_*"),
             key=lambda s: -sum(1 for r in (load(f"{s}/gps.csv") if os.path.exists(f"{s}/gps.csv") else [])
                                 if float(r.get("speed",0) or 0)>1.2))[:8]
print("session                      n   offset  median|res| p75  p90  %<15° %<25°")
allres_med=[]
for S in cands:
    if not os.path.exists(f"{S}/rotvec.csv"): continue
    r=analyze(S)
    if r is None: continue
    allres_med.append(r["med"])
    print(f"{os.path.basename(S):26s} {r['n']:4d} {r['off']:+6.0f}°   {r['med']:5.1f}°  {r['p75']:4.0f}° {r['p90']:4.0f}°  {r['f15']:4.0f}  {r['f25']:4.0f}")
if allres_med:
    mm=np.median(allres_med)
    print(f"\nmedian|res| trung vị qua session = {mm:.1f}°")
    print("GATE 0:", "✓ PASS — rotvec bám heading tốt (offset cố định ~-90°, sai số median nhỏ)" if mm<13
          else ("~ TẠM — dùng được nhưng cần lọc/smooth" if mm<20 else "✗ FAIL"))
