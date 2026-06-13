#!/usr/bin/env bash
# Inference route tay (teach&repeat). Chạy: bash run_infer.sh
# Sửa số bên dưới rồi chạy lại — KHỎI paste lệnh dài (hết lỗi đứt dòng).
# Mỗi run TỰ GHI LOG vào logs/infer_<ngày_giờ>.log (vẫn in ra màn hình như cũ)
# → về nhà phân tích lại được (06-12: 4 run đẹp nhất không có log vì chạy terminal trần).
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
LOG="logs/infer_$(date +%Y%m%d_%H%M%S).log"
echo "[run_infer] log → $LOG"
echo "[run_infer] geosteer-recover-cos = ${GEO:-0}   ·   BẬT geosteer: GEO=0.35 bash run_infer.sh"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --reach-m 6\
  --no-recover \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt \
  --samples 64 --iters 2 \
  --ctrl-lookahead-m 0.5 \
  --heading-cap-deg 35 \
  --pop-confirm-cos 0.5 \
  --steer-smooth 0.1 \
  --steer-trim=-0.04 \
  --xtrack-recover-cos 0 \
  --xtrack-lookahead-m 1.5 \
  --geosteer-recover-cos ${GEO:-0} \
  --geosteer-cap 0.5 \
  --geosteer-div-ticks 4 \
  --turn-slow 0 \
  --throttle-cap 0.10 \
  --cruise-throttle 0.10 \
  --kick-throttle 0.0 \
  --lock-cos 0 \
  --lock-hold-s 10.0 \
  2>&1 | tee -a "$LOG"

# ── KNOB hay chỉnh ──────────────────────────────────────────────
#  --samples/--iters    TICK ĐO THẬT (06-12 đêm, desktop): 32/1=0.5s · 64/2=1.6s ·
#                       128/2=2.9s · 256/2=5.5s/quyết-định. 256/2 = xe đi "MÙ" ~5.5s
#                       (0.3-0.5m/s ≈ 1.5-2.7m ≈ 4-7 subgoal) → "hơi lệch" phần lớn từ đây;
#                       offline 256/2 KHÔNG hơn 64/2 (Δsteer d1 0.041 vs 0.040). KHUYÊN 64/2.
#  --kick-throttle 0.08 kick giờ STEER-AWARE ×(1+0.5|steer|): 0.08 thẳng → 0.12 full-lock
#                       (khớp ma sát đo). kick=0 → đề-pa NGAY TRONG CUA dễ kẹt (scrub >0.10).
#  ⚠️ ROUTE: teach/dựng lại NGAY TRƯỚC buổi chạy (probe 06-12: khác ánh sáng → ccos sập,
#                       30/31 subgoal không qua nổi pop-confirm 0.5 với ảnh khác-buổi).
#  --lock-cos (HOLD)    ⚠ ĐÃ THAY bằng --xtrack-recover-cos (xem trên). HOLD chỉ đóng băng lái
#                       CŨ (có thể là rác) → để 0. Lock-hold-s vô hại khi lock-cos 0.
#  --steer-smooth 0.2   EMA lái. 0.6 (mặc định) = Ì, bóp nửa lực quẹo → đi thẳng.
#                       Test cua: để 0 (lái tươi, raw thẳng ra bánh). Êm/straight: 0.4.
#  --steer-trim -0.04   ⭐ LỆCH CƠ KHÍ (đo 06-13: bánh chếch PHẢI, AUTO 0/192 tick đánh phải).
#                       AUTO bỏ qua subtrim TX (firmware steer=0→1560µs cứng). ÂM = bù TRÁI.
#                       (-0.08 overcorrect → lệch TRÁI 1m ở park4; -0.04 cân hơn.) Trôi PHẢI →
#                       -0.06; lố TRÁI → -0.02. (Fix gốc: hạ SERVO_CENTER 1560→~1500 firmware, trim 0.)
#  --xtrack-recover-cos 0.35  ⭐⭐ CROSS-TRACK RECOVERY (MỚI 06-13, đã test offline 9/9 unit +
#                       27/28 replay log lỗi bẻ-về-tuyến): cos control-target < 0.35 = mất khớp ảnh
#                       → ĐÈ CEM, lái pure-pursuit HÌNH HỌC về polyline teach (GPS xy + heading
#                       track/tangent). Đây là số hạng VỊ TRÍ visual-servo thiếu = thủ phạm GỐC
#                       "lệch 5m ko biết bẻ về → đâm bụi" (đo 06-13). 0=TẮT (về cơ chế cũ). Hay bẻ
#                       về quá sớm/giật → hạ 0.25; còn chạy mù lâu mới bẻ → nâng 0.45.
#  --xtrack-lookahead-m 1.5  recovery ngắm xa ngần này dọc tuyến. Ngắn(1.0)=bẻ gắt; dài(2.5)=mượt.
#  ⭐⭐⭐ --geosteer-recover-cos 0  PHASE 4 (06-13) = RECOVERY MỚI thay v1 (v1 xoay vòng vì heading
#                       GPS-track 1Hz; xem docs/HANDOFF.md). cos control-target < ngưỡng → lái STANLEY
#                       về tuyến bằng HEADING ROTVEC 50Hz (tự calib offset online). 0=TẮT (mặc định,
#                       chờ review). BẬT TEST BÃI: đặt 0.35 (TẮT --xtrack-recover-cos = để v1 khỏi đụng).
#                       Đã PASS offline: geosteer_validate (sim 16/16) + geosteer_integration_check
#                       (calib-arm + closed-loop + safety). ⚠ RỦI RO #1: dấu steer→yaw chỉ kiểm được
#                       TRÊN XE → --geosteer-div-ticks tự DỪNG nếu xe đi XA tuyến (nghi sai dấu).
#                       PROTOCOL bãi: sân TRỐNG, cap thấp, NGÓN TAY trên STOP (web ⛔ / CH9 manual).
#  --geosteer-cap 0.5   trần |steer| Stanley (0.5=không full-lock→không pivot). Hạ 0.4 nếu gắt.
#  --geosteer-div-ticks 4  |cross| vượt min-pha-recovery 2m liên tục 4 tick (hoặc >8m) → DỪNG (chặn
#                       xoay vòng nếu dấu steer→yaw sai trên xe). 0=tắt detector (KHÔNG khuyên ở bãi).
#  ⚠ --lock-cos để 0: recovery (trên) THAY HOLD. HOLD đóng băng lái RÁC (đo park4: khoá +1.0 → rail
#                       vào bụi) → tắt. Chỉ bật lại lock-cos nếu --xtrack-recover-cos 0 (tắt recovery).
#  --kick-throttle 0.10 cú giật đề-pa lúc đứng yên. Vọt/giật → hạ 0.09. Ko lăn → 0.11.
#  --heading-cap-deg 35 lookahead dừng khi route xoay ≥ ngần này → vào cua target gần
#                       lại, còn overlap. Quẹo muộn → hạ 30/25. Khựng → nâng 45.
#  --ctrl-lookahead-m 1.5  target cách xe ngần này (m). Cua thì để ngắn (1.0–1.5).
#  --turn-slow 0        KHÔNG cắt ga trong cua. Mặc định cắt ~nửa ở full-lock → scrub
#                       kẹt (bug subgoal 3). Full-lock cần NHIỀU ga hơn đi thẳng, ko ít.
#                       Đặt >0 (0.2) lại nếu xe phóng quá đà vào lề khi đã qua được cua.
#  --cruise-throttle 0.12 / --throttle-cap 0.13  ga lúc lăn. Full-lock scrub cần ~0.12
#                       (×1.5 ngưỡng đi thẳng 0.07). Kẹt ở cua → nâng cruise 0.13/0.14;
#                       straight phóng quá → hạ 0.10. (cruise = sàn ga hằng, kick 0 đủ đề-pa.)
