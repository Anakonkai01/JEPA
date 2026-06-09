#!/usr/bin/env python3
"""Pre-encode all recorded frames through the frozen V-JEPA encoder -> data/latents/.

Run once after sync_dataset.py; the nav graph / pooled baseline then load the cache.
Encoder = torch.hub vjepa2_1_vit_large_384 (hardcoded in engine/encode.py); CLI args only.
    PYTHONPATH=src python scripts/encode_dataset.py --raw-dir data/raw_kds \
        --out-dir data/latents_kds --image-size 384
"""
from jepa_wm.engine.encode import main

if __name__ == "__main__":
    main()
