#!/usr/bin/env bash
# META-STYLE SINGLE-GOAL (control-only) — chụp 1 ẢNH goal, để CEM lái thẳng tới nó.
#   Chạy:  bash run_goal.sh data/routes/manual/<tên>/000.jpg
#   hoặc:  GOAL=data/routes/manual/<tên>/000.jpg bash run_goal.sh
#
# ĐÂY LÀ KIỂU META (V-JEPA 2-AC reach): KHÔNG subgoal-chain, KHÔNG cosine-pop, KHÔNG localize.
#   Mỗi tick CEM tối thiểu patch-L1 (lighting-robust, cem.py) giữa tương-lai-dự-đoán và ẢNH GOAL,
#   chạy MÃI tới khi BẠN tự dừng (Ctrl-C) — như Meta đánh giá "đạt" từ ngoài vòng. → NÉ luôn tường
#   descriptor/cosine (xem docs/HANDOFF.md: cosine chỉ dùng cho pop, control đã patch-L1).
#
# ⚠ GIỚI HẠN (giống Meta): goal PHẢI NẰM TRONG TẦM NHÌN / có overlap với view hiện tại — CEM cần
#   thấy goal mới có gradient để lái. Goal QUANH GÓC / sau tường = landscape phẳng → không lái nổi.
#   ⇒ đặt goal vài mét THẲNG TRƯỚC, nhìn thấy được. Giữ TMIN=0.07 để xe luôn nhúc nhích (đứng yên
#   → speed=0 → lái vô nghĩa, xem CEM_STEERING_FLAT).
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
GOAL="${1:-${GOAL:-}}"
if [ -z "$GOAL" ] || [ ! -f "$GOAL" ]; then
  echo "[run_goal] ⚠ cần ẢNH goal: bash run_goal.sh <đường_dẫn.jpg>  (hoặc GOAL=...)"
  echo "[run_goal]   chưa có ảnh? Mở web (bash run_infer.sh), 📸 SNAP 1 tấm tại chỗ goal → tạo route 1-ảnh"
  echo "[run_goal]   → file lưu ở data/routes/manual/<tên>/000.jpg, rồi: bash run_goal.sh data/routes/manual/<tên>/000.jpg"
  exit 1
fi
LOG="logs/goal_$(date +%Y%m%d_%H%M%S).log"
echo "[run_goal] log → $LOG | META-STYLE SINGLE-GOAL (control-only, CEM patch-L1, KHÔNG pop/cosine)"
echo "[run_goal] goal = $GOAL"
echo "[run_goal] samples=${SMP:-256}/iters=${ITERS:-2} horizon=${HOR:-4} | ga∈[${TMIN:-0.07},${THR:-0.10}] | warm-start=$([ -z "${POLICY-x}" ] && echo TẮT || echo "${POLICY-checkpoints/policy_prior_cd4/best.pt}")"
echo "[run_goal] CEM lái tới goal MÃI — Ctrl-C để DỪNG khi xe tới nơi (Meta đánh giá đạt từ ngoài). Đặt goal TRONG TẦM NHÌN!"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --control-only \
  --goal-image "$GOAL" \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy "${POLICY-}" \
  --no-kickstart-clamp \
  --no-recover \
  --samples ${SMP:-256} --iters ${ITERS:-2} \
  --horizon ${HOR:-4} \
  --score-chunk ${CHUNK:-0} \
  --heading-cap-deg 35 \
  --steer-smooth ${SMOOTH:-0} \
  --steer-trim=-0.04 \
  --turn-slow 0 \
  --throttle-min ${TMIN:-0.07} \
  --throttle-cap ${THR:-0.10} \
  2>&1 | tee -a "$LOG"

# ── KNOB (ENV): GOAL/SMP/ITERS/HOR/TMIN/THR/SMOOTH/POLICY/CHUNK — giống run_infer.sh ───────────
#  POLICY  mặc định TẮT (cold CEM ra ga ổn + lái tốt; warm-start làm ga sụp ~0, xem CEM_STEERING_FLAT).
#          Bật: POLICY=checkpoints/policy_prior_cd4/best.pt bash run_goal.sh <goal>
#  TMIN=0.07 sàn ga (giữ xe chạy → steering landscape không phẳng). THR=0.10 trần ga.
#  ⚠ Goal phải TRONG TẦM NHÌN. Tới nơi xe sẽ loanh quanh goal (không có reach-stop) → Ctrl-C.
