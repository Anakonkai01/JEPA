"""PHASE 4 INTEGRATION CHECK — validate ĐÚNG chuỗi gọi mà inference_loop.py thực hiện
(không chỉ unit từng hàm như geosteer_validate.py). Đây là cái THIẾU lần trước: recovery-v1
'đúng dấu tĩnh' nhưng wiring closed-loop sai → xe xoay. Test mô phỏng per-tick y hệt inference:

  mỗi tick:  cal_hist.append((t,xy)); yaw_track = est_heading(xy, cal_hist, min_move=1.2)
             if yaw_track: cal.add(az, yaw_track);  car_yaw = cal.yaw(az)       # az = rotvec azimuth
  recovery:  steer,cross,_ = path_steer(xy, car_yaw, spd, poly, cum, cap)
  an toàn:   |cross| tăng >0.05 liên tục N tick (hoặc >8m) → DỪNG (divergence-detector)

Gate:
  A) Calibrate tự ARM khi xe chạy thẳng (offset rotvec↔graph recover đúng, not unreliable).
  B) Closed-loop dùng cal.yaw + dấu ĐÚNG → hội tụ về line, divergence KHÔNG fire.
  C) Dấu steer→yaw LẬT (mô phỏng sai trên xe THẬT = Rủi ro #1) → divergence-detector FIRE
     trong N tick (chặn xoay vòng) — bằng chứng lớp an toàn hoạt động.

Chạy:  PYTHONPATH=src python scripts/geosteer_integration_check.py
"""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from jepa_wm.nav.geosteer import HeadingCalibrator, path_steer, project_arc

NP = NF = 0
def chk(n, c, e=""):
    global NP, NF; ok = bool(c); NP += ok; NF += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}  {e}")

def est_heading(car_xy, hist, min_move=1.2):
    """MIRROR inference_loop.est_car_heading: baseline cũ-nhất→hiện-tại >= min_move."""
    for _t, p in hist:
        d = car_xy - p
        if float(np.hypot(d[0], d[1])) >= min_move:
            return float(np.arctan2(d[1], d[0]))
    return None

def straight_route(n=80):
    P = np.array([[i * 1.0, 0.0] for i in range(n)], float)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return P, cum

OFF = 1.20            # offset thật rotvec↔graph (rad) — test có recover được không
HD_NOISE = math.radians(10)
GPS_NOISE = 0.30
DIV_TICKS = 4         # = --geosteer-div-ticks mặc định
CAP = 0.5

# ----------------------------------------------------------------------------
# A) CALIBRATE-ARMING: chạy thẳng dọc +x, feed calibrator y như inference mỗi tick.
# ----------------------------------------------------------------------------
print("=" * 70); print("GATE A — calibrate tự ARM khi xe chạy (feed y hệt inference)"); print("=" * 70)
rng = np.random.default_rng(0)
cal = HeadingCalibrator()
cal_hist = []
x, y, psi = 0.0, 0.0, 0.0           # chạy thẳng +x → true heading 0
v, sdt = 0.5, 0.2
armed_at = None
for k in range(120):
    t = k * sdt
    x += v * math.cos(psi) * sdt; y += v * math.sin(psi) * sdt
    car_xy = np.array([x, y]) + rng.normal(0, GPS_NOISE, 2)   # GPS noisy
    cal_hist.append((t, car_xy))
    while len(cal_hist) > 1 and t - cal_hist[0][0] > 6.0:
        cal_hist.pop(0)
    az = (psi + OFF + rng.normal(0, HD_NOISE))                # rotvec azimuth = true+offset+noise
    yaw_track = est_heading(car_xy, cal_hist, 1.2)
    if yaw_track is not None:
        cal.add(az, yaw_track)
    if armed_at is None and cal.ready():
        armed_at = round(x, 1)
chk("calibrate ARM được (ready)", cal.ready(), f"sau ~{armed_at}m chạy")
chk("offset recover đúng ~OFF", cal.offset is not None and abs((cal.offset - OFF + math.pi) % (2*math.pi) - math.pi) < math.radians(15),
    f"offset={cal.offset:.2f} vs thật {OFF:.2f} spread={cal.spread_deg:.0f}°")
chk("không bị cờ unreliable (rotvec sạch)", not cal.unreliable(), f"spread={cal.spread_deg:.0f}°<25°")

# ----------------------------------------------------------------------------
# Closed-loop dùng cal.yaw(az) — heading ĐÚNG nguồn (rotvec đã khử offset), chuỗi gọi y inference.
# flip=+1: steer>0 → psi giảm (đúng firmware). flip=-1: mô phỏng dấu SAI trên xe (Rủi ro #1).
# ----------------------------------------------------------------------------
def run_closed_loop(flip, y0=3.0, psi0=0.0, T=60.0):
    P, cum = straight_route()
    rng = np.random.default_rng(1)
    cal = HeadingCalibrator(); cal_hist = []
    x, y, psi = 0.0, y0, psi0
    v, sdt, L, dmax = 0.5, 0.02, 0.33, math.radians(30)
    steer = 0.0; t = 0.0; lc = -9.0
    div_streak, div_min = 0, None; fired = False; peak = 0.0
    while t < T:
        # feed calibrator MỖI tick (như inference, khi có GPS) — dùng tick chậm hơn cho realism
        if t - lc >= 0.15:
            car_xy = np.array([x, y]) + rng.normal(0, GPS_NOISE, 2)
            cal_hist.append((t, car_xy))
            while len(cal_hist) > 1 and t - cal_hist[0][0] > 6.0:
                cal_hist.pop(0)
            az = psi + OFF + rng.normal(0, HD_NOISE)
            yt = est_heading(car_xy, cal_hist, 1.2)
            if yt is not None:
                cal.add(az, yt)
            car_yaw = cal.yaw(az)
            if car_yaw is not None and not cal.unreliable():
                s, cross, _ = path_steer(car_xy, car_yaw, v, P, cum, cap=CAP)
                if s is not None:
                    steer = s
                    # divergence-detector y hệt inference (min-based, biên 2m >> GPS noise)
                    div_min = abs(cross) if div_min is None else min(div_min, abs(cross))
                    if abs(cross) > div_min + 2.0:
                        div_streak += 1
                    else:
                        div_streak = 0
                    if (DIV_TICKS > 0 and div_streak >= DIV_TICKS) or abs(cross) > 8.0:
                        fired = True
                        break
            lc = t
        psi += flip * -(v / L) * math.tan(steer * dmax) * sdt
        x += v * math.cos(psi) * sdt; y += v * math.sin(psi) * sdt; t += sdt
        peak = max(peak, abs(project_arc(np.array([x, y]), P, cum)[0]))
    final = abs(project_arc(np.array([x, y]), P, cum)[0])
    return dict(final=final, peak=peak, fired=fired)

print("\n" + "=" * 70); print("GATE B — closed-loop chuỗi-gọi-inference, dấu ĐÚNG → hội tụ, KHÔNG fire"); print("=" * 70)
for nm, y0, p0 in [("lệch TRÁI 3m", 3.0, 0.0), ("lệch PHẢI 3m", -3.0, 0.0), ("trên line +50°", 0.2, math.radians(50))]:
    r = run_closed_loop(+1, y0, p0)
    chk(f"{nm}: hội tụ <0.6m & KHÔNG diverge", r["final"] < 0.6 and not r["fired"],
        f"final={r['final']:.2f}m peak={r['peak']:.1f}m fired={r['fired']}")

print("\n" + "=" * 70); print("GATE C — dấu steer→yaw LẬT (Rủi ro #1) → divergence-detector PHẢI fire"); print("=" * 70)
r = run_closed_loop(-1, 3.0, 0.0)
chk("dấu sai → DỪNG (chặn xoay vòng trên xe)", r["fired"], f"fired={r['fired']} peak={r['peak']:.1f}m")

print("\n" + "=" * 70)
print(f"TỔNG: {NP} pass / {NF} fail —", "✓ INTEGRATION OK" if NF == 0 else "✗ CÓ FAIL")
print("=" * 70)
sys.exit(1 if NF else 0)
