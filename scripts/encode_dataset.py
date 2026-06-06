#!/usr/bin/env python3
"""Pre-encode all recorded frames through the frozen V-JEPA encoder -> data/latents/.

Run once after sync_dataset.py; training then loads the cached latents.
    python scripts/encode_dataset.py --config configs/data/default.yaml
"""
from jepa_wm.engine.encode import main

if __name__ == "__main__":
    main()
