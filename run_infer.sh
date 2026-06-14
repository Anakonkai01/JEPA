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
MTO=${MTIMEOUT:-60}; [ -n "$STEP" ] && MTO=0   # STEP: TẮT timeout (đang đọc landscape, đừng đếm giờ thật)
CHK=${CHUNK:-0}; [ "${HOR:-4}" -gt 4 ] 2>/dev/null && [ -z "$CHUNK" ] && CHK=64   # HOR>4 → auto score-chunk 64 chống OOM 16GB
echo "[run_infer] log → $LOG | PURE-VISUAL CEM (geosteer/HOLD/off-route/GPS ĐỀU TẮT)$([ -n "$STEP" ] && echo '  | 🔬 STEP MODE: mỗi nhịp DỪNG, in landscape E(steer)/E(throt), CHỜ ENTER')"
echo "[run_infer] samples=${SMP:-256}/iters=${ITERS:-2} (256/2 ≈ 5.5s/tick — nhiều-sample CẮT full-lock outlier; ga thấp → đi-mù ít. Nhanh hơn: SMP=64≈1.6s)"
echo "[run_infer] THUẦN VISUAL: --graph none (pop cosine, KHÔNG GPS) | lookahead=${LOOK:-0.5}m | LÁI=raw_steer (smooth=${SMOOTH:-0}) | HOLD=${LOCK:-0} | kickstart-clamp TẮT"
echo "[run_infer] WARM-START policy = $([ -z "${POLICY-x}" ] && echo 'TẮT (CEM cold, --policy rỗng)' || echo "${POLICY-checkpoints/policy_prior_cd4/best.pt}")  ←A/B: 'POLICY= bash run_infer.sh' = TẮT warm-start"
echo "[run_infer]   → pop subgoal khi cos≥manual-reach(${REACHCOS:-0.6}) HOẶC (cos≥near(0.40) & subgoal-kế gần hơn rõ); 2 tick liên tiếp. reach/pop-confirm GPS BỎ QUA."
echo "[run_infer]   GA = THUẦN MODEL: CEM chọn trong [${TMIN:-0}, ${THR:-0.10}], cruise=${CRUISE:-0} (floor TẮT), kick=${KICK:-0}. Model muốn nhả ga để bẻ về thì ĐƯỢC nhả (không bị cruise ghim tốc)."
echo "[run_infer]   ℹ ga: COLD CEM (POLICY=) ra ga 0.05-0.10 bình thường, xe chạy. WARM-START + clamp-tắt → ga sụp ~0 (policy standstill-attractor). Vấn đề gốc = STEERING, không phải ga. (xem docs/CEM_STEERING_FLAT_20260614.md)"
echo "[run_infer] ⚠ TEACH/dựng route NGAY TRƯỚC buổi (cùng ánh sáng) — khác buổi → ccos sập, pop miss. route_from_session.py <session> <tên> --step-m 0.35"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --graph none \
  --floor-no-gps \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy "${POLICY-checkpoints/policy_prior_cd4/best.pt}" \
  --no-kickstart-clamp \
  --no-recover \
  --samples ${SMP:-256} --iters ${ITERS:-2} \
  --horizon ${HOR:-4} \
  --score-chunk $CHK \
  --reach-m ${REACH:-6} \
  --ctrl-lookahead-m ${LOOK:-0.5} \
  --heading-cap-deg 35 \
  --manual-reach-cos ${REACHCOS:-0.6} \
  --manual-timeout-s $MTO \
  --pop-confirm-cos ${POP:-0.5} \
  --steer-smooth ${SMOOTH:-0} \
  --steer-trim=-0.04 \
  --turn-slow 0 \
  --throttle-min ${TMIN:-0} \
  --throttle-cap ${THR:-0.10} \
  --cruise-throttle ${CRUISE:-0} \
  --kick-throttle ${KICK:-0} \
  --lock-cos ${LOCK:-0} \
  --lock-hold-s 10.0 \
  --xtrack-recover-cos 0 \
  --geosteer-recover-cos 0 \
  $([ -n "$STEP" ] && echo --step) \
  --pulse-move ${PULSE:-0.35} \
  --settle-s ${SETTLE:-0.6} \
  2>&1 | tee -a "$LOG"

# ── KNOB (sửa qua ENV: VD `THR=0.12 LOOK=0.6 bash run_infer.sh`) ─────────────────
#  SMP/ITERS  256/2 = field-PROVEN (06-12, ~5.5s/tick). NHƯNG meas_tail 06-14 ĐO: samples
#             16→256 KHÔNG giảm variance/full-lock-tail (giả thuyết "nhiều-sample cắt đuôi" SAI)
#             → ⭐ THỬ NGAY `SMP=64` (~1.6s, offline ≈ 256/2 nhưng ít lái-mù 3.4× → closed-loop
#             nên TỐT HƠN). Default để 256 cho an toàn (đúng config đã thắng); 64 là knob đầu.
#  LOOK=0.5   ⭐ NGẮN cho cua: target gần → còn overlap → đòi quẹo. 06-13 để 2.0 → vào cua
#             ngắm subgoal quanh-góc (out-of-overlap) → CEM ra ~0 (thẳng) → đi thẳng rồi chết.
#  REACHCOS=0.6  LUẬT-1 pop: cos≥ngưỡng = "nhìn giống hệt subgoal" → pop. ⚠ cos CENTERED thang
#             ~[-0.4,0.5] (subgoal kề ~+0.5) → 0.6 vẫn có thể KHÔNG đạt; lúc đó pop dựa LUẬT-2
#             (near 0.40 + subgoal-kế gần hơn). NHÌN cột cos mỗi tick để biết thang thật route mình.
#  POP=0.5    pop-confirm-cos — CHỈ dùng nhánh GPS (đã chết vì --graph none). Để đây cho mode graph.
#  THR=0.10   ga TRẦN (= throttle-cap). Kẹt đề-pa lúc đứng/cua → KICK=0.10
#             (kick steer-aware ×(1+0.5|steer|)). Phóng quá đà → THR=0.08.
#  TMIN=0     ga SÀN (throttle-min). MẶC ĐỊNH 0 = ga ghim hằng THR (cruise=THR). Muốn CEM TỰ
#             CHỌN ga trong dải → đặt TMIN<THR, vd `TMIN=0.05 THR=0.08 bash run_infer.sh`
#             (CEM chọn ∈[0.05,0.08], cruise tự = TMIN nên floor KHÔNG đè lựa chọn CEM).
#             ⚠ Vùng an toàn xe = [-0.16,0.15]; data train chỉ ~±0.1. TMIN/THR > 0.15 = OOD +
#             dễ lật. KHÔNG đặt 0.5/0.8 (gấp ~5× max an toàn) trừ khi cố ý liều.
#  CRUISE=    ghi đè sàn ga (mặc định = TMIN). Hiếm khi cần.
#  SMOOTH=0   LÁI = raw_steer THẲNG (không EMA) — xem quyết định CEM trần. Giật/zigzag thì
#             SMOOTH=0.2-0.3 (EMA: steer=SMOOTH·cũ+(1-SMOOTH)·mới). 0.6 cũ = Ì, bóp lực quẹo.
#  POLICY=    A/B WARM-START. Mặc định = policy_prior_cd4 seed CEM. `POLICY= bash run_infer.sh`
#             (rỗng) = TẮT warm-start → CEM cold-start (init ga=mid-box, lái=0). So 2 run để
#             biết warm-start giúp hay hại. Kickstart-clamp ĐÃ tắt cứng (ga warm-start thuần policy).
#  LOCK=0.10  HOLD đóng băng lái khi cos<ngưỡng (gần-tắt, chỉ khi MẤT HẲN target). =0 để tắt.
#  steer-trim -0.04  ⭐ lệch CƠ KHÍ (bánh chếch PHẢI). Trôi PHẢI → sửa trong file -0.06; lố TRÁI → -0.02.
#  HEADING-CAP 35°  lookahead dừng khi route xoay ≥ → vào cua target gần lại. Quẹo muộn → 30/25.
#  ⚠ ROUTE cùng buổi (probe 06-12: khác sáng → 30/31 subgoal ko qua pop-confirm 0.5).
