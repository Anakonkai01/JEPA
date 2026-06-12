#!/usr/bin/env bash
# Inference route tay (teach&repeat). Chạy: bash run_infer.sh
# Sửa số bên dưới rồi chạy lại — KHỎI paste lệnh dài (hết lỗi đứt dòng).
# Mỗi run TỰ GHI LOG vào logs/infer_<ngày_giờ>.log (vẫn in ra màn hình như cũ)
# → về nhà phân tích lại được (06-12: 4 run đẹp nhất không có log vì chạy terminal trần).
cd /home/pc5070ti/workspace/JEPA
mkdir -p logs
LOG="logs/infer_$(date +%Y%m%d_%H%M%S).log"
echo "[run_infer] log → $LOG"
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/inference_loop.py \
  --web \
  --reach-m 6\
  --no-recover \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt \
  --samples 256 --iters 2 \
  --ctrl-lookahead-m 0.5 \
  --heading-cap-deg 35 \
  --pop-confirm-cos 0.5 \
  --steer-smooth 0.1 \
  --turn-slow 0 \
  --throttle-cap 0.10 \
  --cruise-throttle 0.10 \
  --kick-throttle 0.0 \
  --lock-cos 0.10 \
  --lock-hold-s 10.0 \
  2>&1 | tee -a "$LOG"

# ── KNOB hay chỉnh ──────────────────────────────────────────────
#  --lock-cos 0.30      GIỮ LÁI XUYÊN VÙNG MÙ (MỚI): cos target tụt < 0.30 giữa cua →
#                       đóng băng lái ở cú quẹo cuối (cam kết hoàn tất cua), hết noise/chệch.
#                       Vẫn chệch sớm → nâng 0.40 (giữ sớm hơn). Can thiệp oan → hạ 0.20.
#  --lock-hold-s 4.0    giữ tối đa 4s; quá mà chưa bắt lại lock → DỪNG (khỏi veer 12m). Cua
#                       to cần lâu hơn → nâng 5-6.
#  --steer-smooth 0.2   EMA lái. 0.6 (mặc định) = Ì, bóp nửa lực quẹo → đi thẳng.
#                       Test cua: để 0 (lái tươi, raw thẳng ra bánh). Êm/straight: 0.4.
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
