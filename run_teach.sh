#!/usr/bin/env bash
# Teach route DÀY (chống mất-lock ở cua). Chạy: bash run_teach.sh <tên>
# Lái remote 1 vòng (CH9 ≠ AUTO), CUA thì đi CHẬM + cua RỘNG MƯỢT (đừng pivot gắt).
# Xong: Ctrl+C để LƯU. Cần route_web.py + run_infer.sh (idle) đang chạy để có car_xy.
NAME="${1:?Cần tên route: bash run_teach.sh parkfix2}"
cd /home/pc5070ti/workspace/JEPA
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python scripts/teach_record.py "$NAME" --step-m 0.4
