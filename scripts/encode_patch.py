#!/usr/bin/env python3
"""Pre-encode frames -> frozen V-JEPA 2.1 PATCH tokens (for the V-JEPA-2-AC car model).

    PYTHONPATH=src python scripts/encode_patch.py --raw-dir data/raw_towerpro \
        --out-dir data/latents_towerpro_patch --image-size 256
"""
from jepa_wm.engine.encode_patch import main

if __name__ == "__main__":
    main()
