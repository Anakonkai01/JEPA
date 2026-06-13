#!/usr/bin/env bash
# ĐÊM 06-14 (account-2) — chuỗi tự chạy (frugal, 1 launch): chờ recovery latents xong → train 2
# biến thể alpha → eval cả hai vs baseline. Bundled để KHÔNG tốn nhiều turn (limit).
cd /home/pc5070ti/workspace/JEPA
PY=~/miniforge3/envs/ai/bin/python
flt() { grep -vE "Warning|warn|cache|Skip|deprecat|FutureWarning|self.gen|UserWarning"; }

echo "[chain] $(date +%H:%M:%S) chờ recovery latents (181 towerpro + 28 kds)..."
last=-1; stall=0; t0=$SECONDS
while true; do
  c=$(( $(ls data/latents_towerpro_recovery 2>/dev/null | wc -l) + $(ls data/latents_kds_recovery 2>/dev/null | wc -l) ))
  [ "$c" -ge 209 ] && { echo "[chain] đủ 209 latents"; break; }
  if [ "$c" -eq "$last" ]; then stall=$((stall+1)); else stall=0; fi
  last=$c
  [ "$stall" -ge 5 ] && [ "$c" -gt 50 ] && { echo "[chain] gen DỪNG ở $c (train với partial)"; break; }
  [ $((SECONDS-t0)) -ge 3000 ] && { echo "[chain] timeout, train ở $c"; break; }
  sleep 30
done

echo "[chain] $(date +%H:%M:%S) ====== TRAIN alpha=1.0 → policy_recovery_cd4 ======"
PYTHONPATH=src $PY scripts/train_policy_recovery.py --alpha 1.0 \
  --out-dir checkpoints/policy_recovery_cd4 2>&1 | flt
echo "[chain] $(date +%H:%M:%S) ====== TRAIN alpha=0.6 → policy_recovery_cd4_a06 ======"
PYTHONPATH=src $PY scripts/train_policy_recovery.py --alpha 0.6 \
  --out-dir checkpoints/policy_recovery_cd4_a06 2>&1 | flt

echo "[chain] $(date +%H:%M:%S) ====== EVAL response (baseline vs recovery) ======"
echo "######## alpha=1.0 ########"
PYTHONPATH=src $PY scripts/eval_recovery_response.py \
  --recovery checkpoints/policy_recovery_cd4/best.pt 2>&1 | flt
echo "######## alpha=0.6 ########"
PYTHONPATH=src $PY scripts/eval_recovery_response.py \
  --recovery checkpoints/policy_recovery_cd4_a06/best.pt 2>&1 | flt
echo "[chain] $(date +%H:%M:%S) DONE — đọc verdict, điền §4 docs/NIGHT_20260614.md, chọn ckpt cho run_policy.sh"
