# archive/ — retired files (2026-06-09)

Kept in-repo (not deleted) but **not part of the live pipeline**. Move back to
`scripts/` or `configs/` if you need them again.

## Why each was archived

| File | Reason |
|------|--------|
| `configs/data/default.yaml` | Dead config — nothing loads it. `scripts/encode_dataset.py`→`engine/encode.py` uses argparse (`--raw-dir/--out-dir/--image-size 384`) + hardcoded torch.hub `vjepa2_1_vit_large_384`; the `hf_id: vjepa2-vitl-fpc64-256` (V-JEPA **2.0** 256) and `use_imu: false` fields never drove anything for the car pipeline. |
| `scripts/eval_goal_reaching.py` | Pooled-probe CEM eval (`CEMPlannerLatent`). Superseded by `scripts/eval_goal_reaching_ac.py` (patch-token `CEMPlannerAC`, the verified one). |
| `scripts/exp_motion_probe.py` | One-off experiment that disproved the multi-frame-encode idea (R²(speed)≈0). Conclusion folded into `docs/HANDOFF.md` / plan §D. |
| `scripts/lewm_overnight.py` | LeWM k-fold/sweep orchestration — finished, results in `docs/LEWM_OVERNIGHT.md`. |
| `scripts/lewm_sweep.py` | LeWM hyperparam sweep — finished. |
| `scripts/lewm_cem_dryrun.py` | LeWM CEM dry-run probe — finished. |

## Still LIVE (NOT archived) — kept as baselines for the thesis
- LeWM baseline: `configs/model/leworldmodel.yaml`, `configs/train/lewm.yaml`,
  `scripts/train_lewm.py`, `scripts/eval_lewm.py`.
- Pooled `vjepa_ac` baseline: `configs/{model/vjepa_ac.yaml, train/vjepa_ac*.yaml}`,
  `scripts/train.py`.
- `scripts/encode_dataset.py` (pooled single-frame latents — needed to rebuild the nav graph).
