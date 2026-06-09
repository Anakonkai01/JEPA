#!/bin/bash
# Overnight experiment queue — run all ablations sequentially.
# Assumes v1 (vjepa_ac_car) is already running. This script runs after v1 finishes.
# Usage: bash scripts/train_overnight.sh >> logs/overnight.log 2>&1 &

set -e
cd "$(dirname "$0")/.."
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate ai

export PYTHONPATH=src

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── 1. Baseline: pooled vjepa_ac_pool (fastest, ~1-2h) ────────────────────────
log "=== START: vjepa_ac_pool baseline ==="
python scripts/train.py \
  --config configs/train/vjepa_ac_pool_towerpro.yaml configs/model/vjepa_ac.yaml \
  >> logs/train_ac_pool_baseline.log 2>&1
log "=== DONE: vjepa_ac_pool baseline ==="

# ── 2. Ablation: minimal state [speed, gz] ────────────────────────────────────
log "=== START: vjepa_ac_car_minimal (state=[speed,gz]) ==="
python scripts/train_ac_car.py \
  --config configs/train/vjepa_ac_car_minimal.yaml configs/model/vjepa_ac_car_minimal.yaml \
  >> logs/train_ac_car_minimal.log 2>&1
log "=== DONE: vjepa_ac_car_minimal ==="

# ── 3. Ablation: predict_residual=True ────────────────────────────────────────
log "=== START: vjepa_ac_car_residual (predict_residual=True) ==="
python scripts/train_ac_car.py \
  --config configs/train/vjepa_ac_car_residual.yaml configs/model/vjepa_ac_car_residual.yaml \
  >> logs/train_ac_car_residual.log 2>&1
log "=== DONE: vjepa_ac_car_residual ==="

log "=== ALL EXPERIMENTS DONE ==="
