"""Validate OFFLINE bộ cross-track recovery hình học (src/jepa_wm/nav/geosteer.py).
Gate 2 (unit: dấu controller + rotvec + calibrator) + Gate 3 (SIM closed-loop hội tụ).
Đây là cái THIẾU ở recovery v1 (chỉ kiểm dấu tĩnh, không mô phỏng động học → xe xoay vòng trên xe).
Chạy:  PYTHONPATH=src python scripts/geosteer_validate.py
Gate 0 (rotvec có dùng được không, trên data thật) = scripts/geosteer_rotvec_check.py.
"""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from jepa_wm.nav.geosteer import path_steer, project_arc, rotvec_to_azimuth, HeadingCalibrator, wrap_pi

NP = NF = 0
def chk(n, c, e=""):
    global NP, NF; ok = bool(c); NP += ok; NF += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}  {e}")

def route(kind, n=60):
    if kind == "thẳng":
        P = np.array([[i*1.0, 0.0] for i in range(n)], float)
    else:
        th = np.linspace(0, math.radians(80), n); R = 25.0
        P = np.stack([R*np.sin(th), R*(1-np.cos(th))], 1)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return P, cum

# ---------- GATE 2: UNIT (dấu) ----------
print("="*68); print("GATE 2 — UNIT (dấu controller / rotvec / calibrator)"); print("="*68)
P, cum = route("thẳng", 40)
def st(xy, yaw, v=0.5): return path_steer(np.array(xy, float), yaw, v, P, cum)[0]
chk("lệch TRÁI → steer PHẢI(+)", st([5,2], 0.0) > 0.2)
chk("lệch PHẢI → steer TRÁI(-)", st([5,-2], 0.0) < -0.2)
chk("trên line mũi dọc → ~0", abs(st([5,0], 0.0)) < 0.1)
chk("mũi lệch TRÁI 30° → PHẢI về", st([5,0], math.radians(30)) > 0.2)
chk("mũi quay NGƯỢC 120° → cap (quay về)", abs(st([5,0], math.radians(120))) > 0.49)
chk("v<vmin (đứng yên) → giảm |steer| (chống pivot)", abs(st([5,3], 0.0, 0.05)) < 0.25)
chk("rotvec identity → 0°", abs(math.degrees(rotvec_to_azimuth(0,0,0))) < 1)
chk("rotvec Z-90° → |az|=90 (cùng trục)", abs(abs(math.degrees(rotvec_to_azimuth(0,0,0.7071)))-90) < 2)
cal = HeadingCalibrator(min_pairs=6); rng = np.random.default_rng(1); OFF = 0.7
for _ in range(20):
    yg = rng.uniform(-math.pi, math.pi)
    cal.add(wrap_pi(yg+OFF+rng.normal(0, math.radians(8))), yg)
chk("calibrator recover offset 0.7", abs(wrap_pi(cal.offset-OFF)) < math.radians(10),
    f"offset={cal.offset:.2f} spread={cal.spread_deg:.0f}°")

# ---------- GATE 3: SIM closed-loop ----------
print("\n" + "="*68); print("GATE 3 — SIM closed-loop (xe bicycle + GPS 1Hz noise + heading rotvec noise)")
print("  HỘI TỤ = final_cross<0.6m & peak<8m (không diverge)"); print("="*68)
def sim(P, cum, x, y, psi, ctrl_dt, cap, v=0.5, L=0.33, dmax=math.radians(30),
        hd_noise=math.radians(13), gps_noise=0.44, T=60.0):
    rng = np.random.default_rng(0); sdt = 0.02; steer = 0.0
    gps = np.array([x, y]); lg = lc = -9; t = 0.0; peak = 0.0
    while t < T:
        if t-lg >= 1.0: gps = np.array([x, y]) + rng.normal(0, gps_noise, 2); lg = t
        if t-lc >= ctrl_dt:
            s, _, _ = path_steer(gps, psi+rng.normal(0, hd_noise), v, P, cum, cap=cap)
            if s is not None: steer = s
            lc = t
        psi += -(v/L)*math.tan(steer*dmax)*sdt        # steer>0=PHẢI=CW=psi giảm
        x += v*math.cos(psi)*sdt; y += v*math.sin(psi)*sdt; t += sdt
        peak = max(peak, abs(project_arc(np.array([x, y]), P, cum)[0]))
    return abs(project_arc(np.array([x, y]), P, cum)[0]), peak

ICs = [("lệch TRÁI 3m dọc", 0, 3, 0.0), ("lệch PHẢI 3m dọc", 0, -3, 0.0),
       ("lệch TRÁI 2m +45°", 0, 2, math.radians(45)), ("trên line +60°", 0, 0.2, math.radians(60))]
for kind in ["thẳng", "cong"]:
    P, cum = route(kind)
    for cap, dt in [(0.5, 0.15), (0.5, 1.5)]:
        ok_n = 0
        for nm, x0, y0, p0 in ICs:
            fc, pk = sim(P, cum, x0, y0, p0, dt, cap)
            ok = fc < 0.6 and pk < 8.0; ok_n += ok
        chk(f"route {kind:5s} cap{cap} tick{dt}s → {ok_n}/4 hội tụ", ok_n >= 3)

print("\n" + "="*68)
print(f"TỔNG: {NP} pass / {NF} fail —", "✓ TẤT CẢ GATE OFFLINE PASS" if NF == 0 else "✗ CÓ FAIL")
print("="*68)
sys.exit(1 if NF else 0)
