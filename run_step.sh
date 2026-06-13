#!/usr/bin/env bash
# ── CHẾ ĐỘ SOI TỪNG-NHỊP (debug planner tại trận) — chạy: bash run_step.sh ──────
# KHÁC run_infer.sh: thêm --step → mỗi tick xe NEUTRAL, in panel "model đang nghĩ gì"
# (E(steer)+E(throt)+contrast) rồi CHỜ phím. KHÔNG tự chạy → không đâm.
#   ENTER = CHẠY đúng 1 nhịp (--pulse-move giây) rồi coast+dừng   [cổng RA ACTION]
#   s     = nhìn lại trên FRAME MỚI, KHÔNG chạy                   [cổng NHẬN FRAME]
#   q     = bỏ route
# ĐỌC panel: contrast<0.15 = model ĐANG ĐOÁN (đừng cho chạy). đáy@=lái model thích.
# E(throt) đáy@0.000 = model không muốn đi. (tham chiếu contrast in-domain ≈0.45)
#
# Pure-visual SẠCH: tắt geosteer/xtrack/HOLD (đang soi MODEL, không phải GPS-recovery).
# CEM 64/2 cho re-look (bấm s) nhanh; sweep 21-nấc trong panel mới là landscape thật.
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
LOG="logs/step_$(date +%Y%m%d_%H%M%S).log"
echo "[run_step] log → $LOG   ·   ENTER=chạy1nhịp · s=nhìn-lại(frame mới) · q=bỏ"
echo "[run_step] ⚠ RE-TEACH route NGAY TRƯỚC (khác sáng → cos sập). throttle-cap=${THR:-0.08}"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --step \
  --reach-m 4 \
  --no-recover \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt \
  --samples ${SMP:-64} --iters ${ITERS:-2} \
  --horizon ${HOR:-6} \
  --ctrl-lookahead-m ${LOOK:-1.5} \
  --heading-cap-deg 35 \
  --pop-confirm-cos ${POP:-0.2} \
  --steer-smooth ${SMOOTH:-0.1} \
  --steer-trim=-0.04 \
  --xtrack-recover-cos 0 \
  --geosteer-recover-cos 0 \
  --lock-cos 0 \
  --turn-slow 0 \
  --throttle-cap ${THR:-0.08} \
  --cruise-throttle ${THR:-0.08} \
  --kick-throttle ${KICK:-0.10} \
  --pulse-move ${PULSE:-0.35} \
  --settle-s ${SETTLE:-0.8} \
  2>&1 | tee -a "$LOG"
