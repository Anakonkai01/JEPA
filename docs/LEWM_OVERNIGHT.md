# LeWM Overnight Pipeline

This is the offline-only pipeline for the TowerPro data and old/new servo
comparison. It trains LeWorldModel variants, evaluates them on held-out synced
sessions, and runs CEM planner dry-runs on recorded validation windows. It does
not send commands to the car.

## Why The New Data Uses Sync

The Android recorder now writes frame timestamps at scene/exposure time
(`t_ms`) and includes `dcam_ms`, so the old fixed camera-delta correction is not
applied. Sync is still required because telemetry is sampled separately from
frames. Training should condition every image at `t_scene_ms` on telemetry
interpolated at that same time, reject frame times outside the telemetry range,
reject large telemetry gaps, and keep only `mode == RECORD`.

The training files are:

- `actions_synced.csv`
- `imu_synced.csv`

Do not train LeWM directly from raw `actions.csv`.

## Action Semantics

KDS 680HV and TowerPro commands are not the same physical steering angle. The
logged `steering` value is the controller command, not a measured wheel angle.
The old KDS data is useful for comparison and possibly pretraining, but TowerPro
held-out performance is the primary acceptance target.

For `frame_skip > 1`, the dataset now supports `action_aggregation=block_mean`.
This averages all synced action rows between sampled frames, matching the LeWM
paper's action-block setup and avoiding the old behavior where skip-5 used only
one command and ignored the intermediate commands.

Throttle is much smaller numerically than steering in the logs, so overnight
experiments use:

```yaml
data:
  action_scale: [1.0, 6.67]
```

That brings the TowerPro throttle range of roughly `[-0.15, +0.15]` into model
units near `[-1, +1]`.

## Overnight Command

```bash
PYTHONPATH=src python scripts/lewm_overnight.py
```

The runner writes:

- `runs/lewm_overnight/<timestamp>/manifest.json`
- `runs/lewm_overnight/<timestamp>/results.json`
- `runs/lewm_overnight/<timestamp>/report.md`
- `checkpoints/overnight/<experiment>/<stage>/leworldmodel/best.pt`

If CUDA is not visible, the runner stops before long CPU training unless
`--allow-cpu` is explicitly passed.

## Experiment Queue

1. TowerPro only, fs5, block-mean actions, emb256, lambda 0.1
2. TowerPro only, emb128
3. TowerPro only, fs3
4. TowerPro only, lambda 0.2
5. KDS pretrain, then TowerPro finetune
6. Mixed old/new naive
7. Mixed old/new with scalar domain token

The mixed domain-token model appends one scalar old/new servo token to the
action vector and therefore uses `model.action_dim=3`.

## Offline Acceptance

Use TowerPro held-out sessions as the main target. A useful checkpoint should:

- beat the identity/no-change latent baseline: `rollout1_ratio < 1.0`
- preferably reach `rollout1_ratio < 0.95`
- keep nontrivial action sensitivity
- avoid collapsed latents, visible as very low `eff_rank` or near-zero `emb_std`
- produce CEM dry-run scores below random mean on validation windows

Validation loss alone is not enough; it can improve while the model still behaves
like an identity predictor.
