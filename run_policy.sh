#!/usr/bin/env bash
# ── CONTROLLER LEARNED-POLICY (UPSIDE đêm 06-14) ──────────────────────────────
# action = policy BC TRỰC TIẾP (1 forward <1ms), BỎ CEM. Hai lý do: (1) "chậm mới ăn" =
# cần NHIỀU quyết-định-tốt/mét, policy quyết 5Hz → ít lái-mù; (2) chỉ policy RECOVERY-AUGMENTED
# mới có khả năng BẺ-VỀ khi lệch làn (geosteer đã bỏ → đây là recovery duy nhất còn lại).
# ⚠ DEFAULT = policy_recovery_cd4 (augment lệch-làn). Augment pooled-latent là PROXY YẾU →
#   transfer chưa chắc → PHẢI probe --step trên xe (nhấc xe lệch, đọc dấu steer) TRƯỚC khi live.
#   Đổi sang baseline (không recovery): POLICY=checkpoints/policy_prior_cd4/best.pt bash run_policy.sh
#
#   STEP=1 bash run_policy.sh   → soi tay + PROBE recovery (nhấc lệch trái→steer phải? phải→trái?).
#   bash run_policy.sh          → LIVE 5Hz (CHỈ sau khi --step thấy dấu recovery đúng).
# Mặc định AN TOÀN: pure-visual, geosteer/xtrack/HOLD tắt, throttle thấp, ngón tay trên STOP.
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
# recovery-augment α=0.6 (DEFAULT, dịu) → α=1.0 (mạnh hơn) → baseline BC (KHÔNG recovery)
POLICY="${POLICY:-checkpoints/policy_recovery_cd4_a06/best.pt}"
[ -f "$POLICY" ] || POLICY="checkpoints/policy_recovery_cd4/best.pt"
[ -f "$POLICY" ] || POLICY="checkpoints/policy_prior_cd4/best.pt"
# mạnh hơn nếu α=0.6 kéo không đủ về line: POLICY=checkpoints/policy_recovery_cd4/best.pt bash run_policy.sh
LOG="logs/policy_$(date +%Y%m%d_%H%M%S).log"
echo "[run_policy] log → $LOG | $([ -n "$STEP" ] && echo 'STEP (validate tay)' || echo 'LIVE 5Hz') | policy=$POLICY | throttle-cap=${THR:-0.10}"
echo "[run_policy] ⚠ RE-TEACH route cùng buổi. STOP sẵn (web⛔/CH9-manual). Probe recovery --step TRƯỚC (augment chưa kiểm xe)."
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --policy "$POLICY" \
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
