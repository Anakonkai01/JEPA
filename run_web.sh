#!/usr/bin/env bash
# Web server (laptop park nối qua Tailscale 100.110.165.40:8060). Chạy: bash run_web.sh
cd /home/pc5070ti/workspace/JEPA
PYTHONPATH=src ~/miniforge3/envs/ai/bin/python scripts/route_web.py
