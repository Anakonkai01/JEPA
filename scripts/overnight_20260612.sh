#!/usr/bin/env bash
# Đêm 2026-06-12 → sáng 13: chain GPU (chạy SAU khi eval 256/2 xong, GPU trống).
#   1) cooldown cd4_as3 (auto_steps 3, 2 ep ≈ 6-7h)
#   2) eval B5 trên ckpt mới: eval_ratio + goal-reaching s32i1 + probe_energy turn-only
# Sáng ra đọc: logs/train_ac_car_cd4_as3.log + logs/eval_*_cd4_as3*.log + HANDOFF.
set -e
cd /home/pc5070ti/workspace/JEPA

# B4: split.json PHẢI copy trước (thiếu -> tự sinh split KHÁC -> eval sai)
mkdir -p checkpoints/vjepa_ac_car_cd4_as3/vjepa_ac_car
cp checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/split.json checkpoints/vjepa_ac_car_cd4_as3/vjepa_ac_car/

PYTORCH_ALLOC_CONF=expandable_segments:True PYTHONPATH=src \
  ~/miniforge3/envs/ai/bin/python -u scripts/train_ac_car.py \
  --config configs/train/vjepa_ac_car_cd4_as3.yaml configs/model/vjepa_ac_car.yaml \
  > logs/train_ac_car_cd4_as3.log 2>&1

CKPT=checkpoints/vjepa_ac_car_cd4_as3/vjepa_ac_car/best.pt
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/eval_ratio_ac.py \
  --checkpoint "$CKPT" > logs/eval_ratio_cd4_as3.log 2>&1

PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/eval_goal_reaching_ac.py \
  --checkpoint "$CKPT" --distances 1 2 4 8 --n-windows 60 --samples 32 --iters 1 \
  --policy checkpoints/policy_prior/best.pt --throttle-min 0 --throttle-max 0.10 \
  > logs/eval_goal_cd4_as3_s32i1.log 2>&1

PYTHONPATH=src ~/miniforge3/envs/ai/bin/python -u scripts/probe_energy.py \
  --checkpoint "$CKPT" --turn-only -d 4 --n-windows 60 \
  > logs/probe_energy_cd4_as3_turn.log 2>&1

echo "[overnight] DONE $(date)" >> logs/train_ac_car_cd4_as3.log
