#!/bin/bash
# Wait for v1 training to finish, then launch overnight ablations.
# Usage: bash scripts/watchdog_then_ablations.sh >> logs/overnight.log 2>&1 &

cd "$(dirname "$0")/.."
LOG=logs/train_ac_car_v1.log

echo "[watchdog] $(date): waiting for v1 to finish (monitoring $LOG)..."
until grep -qE "DONE best_val|early-stop" "$LOG" 2>/dev/null; do
    sleep 30
done
echo "[watchdog] $(date): v1 finished! launching ablations..."

bash scripts/train_overnight.sh
echo "[watchdog] $(date): all done."
