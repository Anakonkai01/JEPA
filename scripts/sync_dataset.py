#!/usr/bin/env python3
"""Re-pair recorded frames with actions/IMU (δ_cam-corrected) -> *_synced.csv.

Thin wrapper around jepa_wm.data.sync. Run from the repo root:
    python scripts/sync_dataset.py                     # all sessions in data/raw
    python scripts/sync_dataset.py data/raw/session_X  # one session
"""
from jepa_wm.data.sync import main

if __name__ == "__main__":
    main()
