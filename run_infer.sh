#!/usr/bin/env bash
# Inference route tay (teach&repeat) — PURE-VISUAL CEM.   Chạy: bash run_infer.sh
# Sửa số qua ENV (vd: THR=0.12 bash run_infer.sh) — KHỎI paste lệnh dài (hết lỗi đứt dòng).
# Mỗi run TỰ GHI LOG → logs/infer_<ngày_giờ>.log (vẫn in màn hình).
#
# DEFAULT = config ĐÃ-CHỨNG-MINH ở bãi 06-12 tối đợt-2 ("qua cua nhiều run liên tiếp, RẤT
#   HÀI LÒNG" — lần đầu xe tự qua cua): 256/2 + lookahead NGẮN 0.5 + pop-confirm 0.5 +
#   reach 6 + kick 0. (06-13 đổi lookahead 2.0/128/geosteer rồi BUNG ở bãi → đã revert.)
# GEOSTEER ĐÃ BỎ HOÀN TOÀN (quyết định user 06-14) → đây là PURE-VISUAL, KHÔNG có recovery
#   GPS/rotvec. ⇒ recovery duy nhất (nếu có) = policy recovery-augmented (run_policy.sh).
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
LOG="logs/infer_$(date +%Y%m%d_%H%M%S).log"
echo "[run_infer] log → $LOG | PURE-VISUAL CEM (geosteer bỏ)"
echo "[run_infer] samples=${SMP:-256}/iters=${ITERS:-2} (256/2 ≈ 5.5s/tick — nhiều-sample CẮT full-lock outlier; ga thấp → đi-mù ít. Nhanh hơn: SMP=64≈1.6s)"
echo "[run_infer] throttle=${THR:-0.10} kick=${KICK:-0} pop-confirm=${POP:-0.5} lookahead=${LOOK:-0.5}m reach=${REACH:-6}m steer-smooth=${SMOOTH:-0.1}"
echo "[run_infer] ⚠ TEACH/dựng route NGAY TRƯỚC buổi (cùng ánh sáng) — khác buổi → ccos sập, pop miss. route_from_session.py <session> <tên> --step-m 0.35"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior_cd4/best.pt \
  --no-recover \
  --samples ${SMP:-256} --iters ${ITERS:-2} \
  --horizon ${HOR:-4} \
  --reach-m ${REACH:-6} \
  --ctrl-lookahead-m ${LOOK:-0.5} \
  --heading-cap-deg 35 \
  --pop-confirm-cos ${POP:-0.5} \
  --steer-smooth ${SMOOTH:-0.1} \
  --steer-trim=-0.04 \
  --turn-slow 0 \
  --throttle-cap ${THR:-0.10} \
  --cruise-throttle ${THR:-0.10} \
  --kick-throttle ${KICK:-0} \
  --lock-cos ${LOCK:-0.10} \
  --lock-hold-s 10.0 \
  --xtrack-recover-cos 0 \
  --geosteer-recover-cos 0 \
  2>&1 | tee -a "$LOG"

# ── KNOB (sửa qua ENV: VD `THR=0.12 LOOK=0.6 bash run_infer.sh`) ─────────────────
#  SMP/ITERS  256/2 (proven, ~5.5s/tick) — nhiều sample CẮT đuôi full-lock (energy phẳng
#             → ít sample bốc ±1). Ga THẤP nên đi-mù 5.5s vẫn dịch ít. Nhanh hơn: SMP=64
#             (~1.6s) — chỉ dùng nếu đuôi full-lock OK (xem logs/meas_tail đêm 06-14).
#  LOOK=0.5   ⭐ NGẮN cho cua: target gần → còn overlap → đòi quẹo. 06-13 để 2.0 → vào cua
#             ngắm subgoal quanh-góc (out-of-overlap) → CEM ra ~0 (thẳng) → đi thẳng rồi chết.
#  POP=0.5    pop-confirm-cos. Latch + geo-confirm (<1.5m) đã fix pop-stuck (06-12 đợt-2).
#             Khác buổi/route thẳng tự-giống cos sập → POP=0 (pop thuần GPS, reach 6m) né kẹt.
#  THR=0.10   ga cruise=cap (sàn hằng, kick 0 đủ đề-pa êm). Kẹt đề-pa lúc đứng/cua → KICK=0.10
#             (kick steer-aware ×(1+0.5|steer|)). Phóng quá đà → THR=0.08.
#  SMOOTH=0.1 EMA lái. 0.6 (mặc định cũ) = Ì → bóp nửa lực quẹo → đi thẳng. Twitchy → 0.2-0.3.
#  LOCK=0.10  HOLD đóng băng lái khi cos<ngưỡng (gần-tắt, chỉ khi MẤT HẲN target). =0 để tắt.
#  steer-trim -0.04  ⭐ lệch CƠ KHÍ (bánh chếch PHẢI). Trôi PHẢI → sửa trong file -0.06; lố TRÁI → -0.02.
#  HEADING-CAP 35°  lookahead dừng khi route xoay ≥ → vào cua target gần lại. Quẹo muộn → 30/25.
#  ⚠ ROUTE cùng buổi (probe 06-12: khác sáng → 30/31 subgoal ko qua pop-confirm 0.5).
