#!/usr/bin/env bash
# ── CONTROLLER LEARNED-POLICY (pivot đêm 06-14) ───────────────────────────────
# action = policy BC TRỰC TIẾP (1 forward <1ms), BỎ CEM. Vì sao: phát hiện user "chậm
# mới ăn" = cần NHIỀU quyết-định-tốt / mét. CEM chậm (0.5–5.5s/tick) → phải bò + lái-mù
# nhiều. Policy quyết ở 5Hz+ → ít lái-mù DÙ chạy bình thường.
# Bằng chứng OFFLINE (cd4, val): |Δsteer| 0.014 thẳng / 0.055 full-lock; sign-match recovery
#   98% (|steer|>0.7). ⚠ CHƯA kiểm closed-loop trên xe → VALIDATE --step TRƯỚC.
#
#   STEP=1 bash run_policy.sh   → soi tay: xem policy quyết gì mỗi điểm + E(steer) CEM để so,
#                                 gate từng nhịp (ENTER chạy / s nhìn-lại). LÀM CÁI NÀY TRƯỚC.
#   bash run_policy.sh          → LIVE 5Hz (sau khi --step thấy policy quyết hợp lý).
# Mặc định AN TOÀN: pure-visual, geosteer/xtrack/HOLD tắt, throttle thấp, ngón tay trên STOP.
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
LOG="logs/policy_$(date +%Y%m%d_%H%M%S).log"
echo "[run_policy] log → $LOG | $([ -n "$STEP" ] && echo 'STEP (validate tay)' || echo 'LIVE 5Hz') | throttle-cap=${THR:-0.10}"
echo "[run_policy] ⚠ RE-TEACH route cùng buổi. STOP sẵn (web⛔/CH9-manual). Policy CHƯA kiểm trên xe → STEP=1 trước."
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --policy checkpoints/policy_prior_cd4/best.pt \
  --policy-only \
  $([ -n "$STEP" ] && echo --step) \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --reach-m 4 --no-recover \
  --pop-confirm-cos ${POP:-0} \
  --ctrl-lookahead-m ${LOOK:-1.5} \
  --heading-cap-deg 35 \
  --steer-smooth ${SMOOTH:-0.2} \
  --steer-trim=-0.04 \
  --xtrack-recover-cos 0 --geosteer-recover-cos 0 --lock-cos 0 --turn-slow 0 \
  --throttle-cap ${THR:-0.10} \
  --cruise-throttle ${CRUISE:-0.07} \
  --kick-throttle ${KICK:-0.10} \
  --rate ${RATE:-5} \
  --pulse-move ${PULSE:-0.35} --settle-s ${SETTLE:-0.6} \
  2>&1 | tee -a "$LOG"
