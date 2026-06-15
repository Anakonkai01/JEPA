#!/usr/bin/env bash
# Resume the open-loop demo precompute over ALL remaining VAL sessions.
# Skips sessions that already have data/demo/<session>/demo.json. Safe to re-run.
set -u
cd /home/pc5070ti/workspace/JEPA
PY=~/miniforge3/envs/ai/bin/python
LOG=data/demo/precompute_all.log
echo "==== resume precompute $(date) ====" >>"$LOG"

mapfile -t TODO < <(PYTHONPATH=src $PY - <<'PYEOF'
import torch, json
from pathlib import Path
ck="checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt"
roots=torch.load(ck,map_location="cpu",weights_only=False)["cfg"]["data"]["roots"]
avail=set()
for r in roots:
    avail|={p.stem for p in Path(r["patch_dir"]).glob("*.npy")}
sp=Path("checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/split.json")
val=json.load(open(sp if sp.exists() else "docs/split_vjepa_ac_car.json"))["val"]
done={p.name for p in Path("data/demo").glob("session_*") if (p/"demo.json").exists()}
for s in val:
    if s in avail and s not in done: print(s)
PYEOF
)

echo "TODO=${#TODO[@]} sessions" | tee -a "$LOG"
i=0
for s in "${TODO[@]}"; do
  i=$((i+1))
  echo "[$i/${#TODO[@]}] $s  $(date +%H:%M:%S)" | tee -a "$LOG"
  PYTHONPATH=src $PY scripts/demo_precompute.py "$s" -d 4 >>"$LOG" 2>&1 \
    && echo "  OK $s" | tee -a "$LOG" \
    || echo "  FAIL $s" | tee -a "$LOG"
done
echo "==== done $(date) ====" | tee -a "$LOG"
