"""Geometric steering helpers cho recovery khi visual-servo MẤT khớp (cos thấp).

Bối cảnh (đo 06-13 ở park): control thuần-visual không có phản hồi VỊ TRÍ → xe lệch
line → cos sập → CEM noise → đâm bụi. Recovery v1 (pure-pursuit dùng heading GPS-track
1Hz) XOAY VÒNG vì: full-lock + heading trễ/vắng (GPS 1Hz, xe chậm) + tốc thấp → pivot
tại chỗ. Bài học → module này:

  1) HEADING từ rotvec phone (50Hz, Phase-0 đo: bám GPS-track median ~10°, offset
     rotvec↔graph ~hằng nhưng ĐỔI giữa buổi → calibrate ONLINE) thay vì GPS-track.
  2) Controller pure-pursuit CÓ CAP (không bão hoà ±1) + lookahead theo tốc độ →
     cua về line MƯỢT, KHÔNG pivot. + cấm lái mạnh khi gần đứng yên.

Thuần numpy, không phụ thuộc torch → unit-test + SIM closed-loop offline được.
Quy ước góc: math (CCW dương, 0=+x trục graph). steer_norm: + = PHẢI (khớp firmware:
steer>0 → µs cao → phải = quay CW = yaw giảm). Nên quẹo về yaw TĂNG (trái) → steer ÂM.
"""
from __future__ import annotations

import math
import numpy as np


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# --------------------------------------------------------------------------- #
# HEADING từ Android ROTATION_VECTOR (rx,ry,rz = axis*sin(θ/2))
# --------------------------------------------------------------------------- #
def rotvec_to_azimuth(rx: float, ry: float, rz: float) -> float:
    """rotvec → azimuth (rad). w=sqrt(1-|v|²); R từ quaternion; azimuth=atan2(R01,R11).
    Đây là hướng THÔ của phone (chưa canh trục car↔graph) — cần trừ offset (HeadingCalibrator)."""
    n = rx * rx + ry * ry + rz * rz
    w = math.sqrt(max(0.0, 1.0 - n))
    R01 = 2.0 * (rx * ry - w * rz)
    R11 = 1.0 - 2.0 * (rx * rx + rz * rz)
    return math.atan2(R01, R11)


class HeadingCalibrator:
    """Ước lượng ONLINE offset (azimuth_rotvec − yaw_graph) + health-check.

    yaw_graph thật lấy từ GPS-track (atan2 dịch chuyển xy graph) khi xe chạy đủ nhanh +
    đủ xa (baseline) → ghép với azimuth_rotvec cùng thời điểm → offset = circular-median.
    Offset ~hằng trong 1 buổi (Phase-0) nhưng đổi giữa buổi → tự canh lại mỗi run.
    Health: nếu spread residual lớn (rotvec loạn — 1/8 session Phase-0) → unreliable()."""

    def __init__(self, min_pairs: int = 6, max_pairs: int = 40):
        self.min_pairs = min_pairs
        self.max_pairs = max_pairs
        self._d: list[float] = []          # azimuth_rotvec − yaw_graph (rad)
        self.offset: float | None = None
        self.spread_deg: float = 999.0

    def add(self, azimuth_rotvec: float, yaw_graph_track: float) -> None:
        self._d.append(wrap_pi(azimuth_rotvec - yaw_graph_track))
        if len(self._d) > self.max_pairs:
            self._d.pop(0)
        if len(self._d) >= self.min_pairs:
            d = np.asarray(self._d)
            # circular median (offset cực tiểu hoá median|res|)
            best = (1e9, 0.0)
            for c in np.linspace(-math.pi, math.pi, 180):
                m = float(np.median(np.abs((d - c + math.pi) % (2 * math.pi) - math.pi)))
                if m < best[0]:
                    best = (m, float(c))
            self.offset = best[1]
            res = (d - self.offset + math.pi) % (2 * math.pi) - math.pi
            self.spread_deg = float(np.degrees(np.median(np.abs(res))))

    def ready(self) -> bool:
        return self.offset is not None

    def unreliable(self) -> bool:
        """rotvec lệch GPS-track quá nhiều (mag nhiễu) → đừng tin heading rotvec."""
        return self.ready() and self.spread_deg > 25.0

    def yaw(self, azimuth_rotvec: float) -> float | None:
        """azimuth rotvec → yaw trong graph-frame (rad). None nếu chưa calibrate."""
        if self.offset is None:
            return None
        return wrap_pi(azimuth_rotvec - self.offset)


# --------------------------------------------------------------------------- #
# Pure-pursuit CÓ CAP về polyline (controller recovery)
# --------------------------------------------------------------------------- #
def project_arc(car_xy, poly, cum):
    """Chiếu xe lên polyline → (cross_track_signed[+=TRÁI], s_along, seg_idx).
    cross dùng để báo lệch; s_along để đặt điểm lookahead."""
    car_xy = np.asarray(car_xy, np.float64)
    poly = np.asarray(poly, np.float64)
    best = (1e18, 0.0, 0.0, 0)
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        ab = b - a
        L2 = float(ab @ ab)
        if L2 < 1e-12:
            continue
        t = float(np.clip(((car_xy - a) @ ab) / L2, 0.0, 1.0))
        proj = a + t * ab
        d = float(np.hypot(*(car_xy - proj)))
        if d < best[0]:
            cross = ((car_xy[0] - proj[0]) * (-ab[1]) + (car_xy[1] - proj[1]) * ab[0]) / math.sqrt(L2)
            s = float(cum[i] + t * (cum[i + 1] - cum[i]))
            best = (d, cross, s, i)
    return best[1], best[2], best[3]


def lookahead_point(poly, cum, s_along, lookahead_m):
    s_t = s_along + max(0.0, lookahead_m)
    poly = np.asarray(poly, np.float64)
    cum = np.asarray(cum, np.float64)
    if s_t >= cum[-1]:
        return poly[-1]
    k = int(np.searchsorted(cum, s_t) - 1)
    k = max(0, min(k, len(poly) - 2))
    seg = float(cum[k + 1] - cum[k])
    f = 0.0 if seg < 1e-9 else (s_t - float(cum[k])) / seg
    return poly[k] + f * (poly[k + 1] - poly[k])


def path_steer(car_xy, car_yaw, speed, poly, cum,
               k_cross=0.6, k_soft=0.5, steer_full_rad=math.radians(35.0),
               cap=0.5, v_min=0.12):
    """Steer hình học về polyline (recovery) — STANLEY (heading-error + cross-track).

    KHÁC pure-pursuit (v1 — suy biến khi xe chĩa RA XA line: ngắm điểm trước mũi vô nghĩa
    → lật ±cap → đi thẳng ra xa): Stanley dùng TIẾP TUYẾN route trực tiếp nên luôn kéo
    heading xe về hướng tuyến + bù cross-track. Ổn định cả khi xe quay ngang/ngược.

      psi_path = hướng tiếp tuyến route tại hình-chiếu xe.
      psi_d    = psi_path − atan2(k_cross·cross_trái, v+k_soft)   # lệch TRÁI → ngắm phải về line
      steer    = clip( −(psi_d − psi_car)/steer_full , −cap, cap )  # quay về psi_d; CCW→steer âm

    car_yaw: heading xe (rad graph-frame, từ rotvec đã calibrate). None → None.
    k_cross: gain cross-track (cao=về gắt, dễ dao động; thấp=về chậm). k_soft: chống chia v→0.
    cap: TRẦN |steer| (0.5 = không full-lock → mượt, chống pivot/over-rotate — fix vụ xoay v1).
    v_min: gần đứng yên → giảm tuyến tính (không bẻ gắt tại chỗ).
    Trả (steer_norm[-cap,cap], cross_track[+=TRÁI], heading_err_deg) hoặc (None,None,None)."""
    if car_yaw is None or poly is None or len(poly) < 2:
        return None, None, None
    poly = np.asarray(poly, np.float64)
    cross, _, seg = project_arc(car_xy, poly, cum)
    seg = int(max(0, min(seg, len(poly) - 2)))
    tang = poly[seg + 1] - poly[seg]
    psi_path = math.atan2(tang[1], tang[0])
    v = max(0.0, speed)
    psi_d = psi_path - math.atan2(k_cross * cross, v + k_soft)   # cross>0(trái)→ngắm phải về line
    turn_err = wrap_pi(psi_d - car_yaw)            # >0: cần quay CCW(trái) → steer âm
    steer = max(-cap, min(cap, -turn_err / steer_full_rad))
    if speed < v_min:                              # gần đứng yên → đừng bẻ gắt (chống pivot)
        steer *= max(0.0, speed / v_min)
    return float(steer), float(cross), float(math.degrees(wrap_pi(psi_path - car_yaw)))
