#!/usr/bin/env bash
# Open-loop steering demo web (port 8070). PLAY không cần GPU (precompute đã xong).
# Precompute 1 session:  PYTHONPATH=src python scripts/demo_precompute.py <session> -d 4
# Mở:  http://localhost:8070   (hoặc Tailscale IP:8070)
cd /home/pc5070ti/workspace/JEPA
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python scripts/demo_web.py
