# LeWorldModel (LeWM) — readable summary

> Source: **"LeWorldModel: Stable End-to-End Joint-Embedding Predictive Architecture
> from Pixels"** — Lucas Maes\*, Quentin Le Lidec\*, Damien Scieur, Yann LeCun,
> Randall Balestriero (arXiv 2603.19312v3, Jun 2026). PDF: `docs/LeWorldModel.pdf`.
> Code: <https://github.com/lucas-maes/le-wm> · Site: <https://le-wm.github.io> ·
> Checkpoints/data: HuggingFace `quentinll/lewm`.
>
> This file is a hand-written digest for quick reference (so we don't re-read the
> 28-page PDF). Our faithful port lives in `src/jepa_wm/models/leworldmodel.py`,
> `src/jepa_wm/engine/losses.py` (SIGReg), `engine/train_lewm.py`.

## TL;DR

LeWM is the **first JEPA that trains stably end-to-end from raw pixels** using only
**two loss terms** (next-embedding MSE + a Gaussian-distribution regularizer), with
**one effective hyperparameter** (λ). No EMA, no stop-gradient, no pretrained/frozen
encoder, no reconstruction, no reward. ~15M params, single GPU, a few hours. Plans
up to 48× faster than foundation-model world models, competitive on 2D/3D control.

**Key contrast with our V-JEPA approach:** our main model (`vjepa_ac`) *freezes* a
pretrained V-JEPA encoder and trains only a predictor. **LeWM is the opposite** — it
learns its *own* encoder from scratch jointly with the predictor. So in this repo LeWM
is an independent, self-contained world model (a strong comparison point), **not** a
head on top of V-JEPA.

## Architecture

Two components, trained jointly end-to-end:

```
o_t ──enc_θ──► z_t          (encoder: pixels → latent)
(z_t, a_t) ──pred_φ──► ẑ_{t+1}   (predictor: latent dynamics, action-conditioned)
```

- **Encoder** = Vision Transformer **Tiny** (~5M): patch 14, 12 layers, 3 heads,
  hidden 192. Take the **[CLS]** token of the last layer, then a **projection** =
  1-layer MLP **with BatchNorm**. The BN matters: the ViT's final LayerNorm would
  otherwise neutralize the anti-collapse objective.
- **Predictor** = causal Transformer (~ViT-S, 6 layers, 16 heads, 10% dropout, ~10M).
  Actions are injected via **AdaLN-zero** (modulation params init to 0 → action
  conditioning ramps in gradually, stabilizes training). Takes a **history of N**
  latents, predicts the next one autoregressively with **temporal causal masking**.
  Followed by its own projector (same BN design as the encoder's).

## Training objective (the whole point)

```
L_LeWM = L_pred + λ · SIGReg(Z)
```

1. **Prediction loss** (teacher-forced): `L_pred = ‖ẑ_{t+1} − z_{t+1}‖²`.
   Alone this collapses (encoder maps everything to a constant).
2. **SIGReg** (Sketched-Isotropic-Gaussian Regularizer) — anti-collapse. Pushes the
   latent distribution toward an isotropic Gaussian **N(0, I)**:
   - Project embeddings onto **M random unit directions** `u⁽ᵐ⁾` (M = 1024).
   - On each 1-D projection apply the **Epps–Pulley** normality test statistic:
     `T = ∫ w(t) |φ_N(t) − φ₀(t)|² dt`, where `φ_N` is the empirical characteristic
     function `mean_n exp(i·t·hₙ)`, `φ₀(t)=e^{−t²/2}` is the standard-normal CF, and
     `w(t)=e^{−t²/2}`. Integral via **trapezoid over `knots` nodes in [0, 3]** (code)
     — the paper text says [0.2, 4]; **the released code uses [0, 3] with 17 knots**,
     which is what we port.
   - `SIGReg(Z) = (1/M) Σ_m T⁽ᵐ⁾`, averaged over time too.
   - By **Cramér–Wold**, matching all 1-D marginals ⇒ matching the full joint, so
     `SIGReg → 0 ⇔ P_Z → N(0, I)`.

**Hyperparameters:** only **M** (projections, performance ~insensitive) and **λ**
(reg weight). Defaults **M = 1024, λ = 0.1**. λ robust in **[0.01, 0.2]** (peaks ~0.09);
λ = 0.5 over-regularizes. λ is the single knob → tune by bisection.

Official training pseudo-code (Alg. 3):
```python
def LeWorldModel(obs, actions, lambd=0.1):
    emb       = encoder(obs)             # (B, T, D)  includes [CLS]→BN projector
    next_emb  = predictor(emb, actions)  # (B, T, D)  causal, AdaLN action cond.
    pred_loss = mse(next_emb[:, :-1], emb[:, 1:])   # next-embedding prediction
    sigreg    = SIGReg(emb.transpose(0, 1))         # over (T, B, D)
    return pred_loss + lambd * sigreg
```
No stop-grad / EMA: gradients flow through **all** components, including the encoder
via both terms.

## Latent planning (inference, Phase-4 for us)

Trajectory optimization in latent space (model fixed):
- Encode current obs → `ẑ₁`; roll the predictor autoregressively under a candidate
  action sequence to horizon H.
- Cost = `‖ẑ_H − z_g‖²` to the **goal-image latent** `z_g = enc(o_g)`.
- Solve `argmin_a C(ẑ_H)` with **CEM** (300 samples, 30 iters on PushT / 10 elsewhere,
  top-30 elites, init σ = 1), then **MPC** receding horizon (H = 5).

## Paper's experimental setup (for reference)

- Offline, reward-free trajectories `(o_{1:T}, a_{1:T})`. **Frame-skip 5**, batch 128,
  sub-trajectories of 4 frames (+ 4 action blocks of 5), frames **224×224**.
- Predictor **history length 3** (PushT/Cube), 1 (TwoRoom). **10 epochs** per env.
- Envs: Push-T, OGBench-Cube (3D arm), Two-Room nav, Reacher. Datasets 10k–20k episodes.
- Ablations: emb-dim threshold ≈ 184 (saturates after); SIGReg #projections & #knots
  ~irrelevant; predictor **ViT-S** best (tiny worse, base no gain); dropout **0.1**
  best; adding a decoder/reconstruction loss **hurts**; CEM ≫ SGD/Adam for planning.
- Extras: latent encodes physical quantities (probing); "surprise" detects implausible
  events; temporal-straightening emerges without being enforced.

## How our port maps to this (RC-car adaptation)

| Paper | Ours (`configs/model/leworldmodel.yaml`, `data/`) |
|-------|----|
| frames 224×224 | 224×224 (resized from 640×360 phone frames) |
| frame-skip 5 (high-rate sim) | `frame_skip=1` — our synced data is already ~10 fps |
| sub-traj 4 frames + action blocks | `seq_len=4`, **one** action per frame (action_dim=2: steering, throttle) |
| batch 128 | 96 (fits the RTX 5070 Ti with headroom) |
| 10 epochs (their data) | high ceiling (200) + **early stopping** on val pred loss |
| M=1024, λ=0.1, knots=17 | same |
| encoder ViT-Tiny p14, predictor ViT-S 6L | same; emb_dim 256 (> collapse threshold) |
| HDF5 gym datasets, Hydra, WandB, stable-* | standalone: `FrameSequenceDataset` + our YAML/TensorBoard loop |

We do **not** install their `stable-pretraining` / `stable-worldmodel` stack (those wrap
gym envs + HDF5 + planning we don't need yet). Only the core model + objective are ported.

**Offline eval we added** (no env needed): multi-step **rollout MSE** vs. encoder latents,
plus **collapse metrics** — per-dim std (≈1 means SIGReg is shaping N(0,I)) and entropy-based
**effective rank** of the latent covariance (≈ emb_dim means no collapse).

## Run it

```bash
PYTHONPATH=src python scripts/train_lewm.py \
    --config configs/train/lewm.yaml configs/model/leworldmodel.yaml
# overrides: --set sigreg.lambd=0.05 train.batch_size=64
# checkpoints -> checkpoints/leworldmodel/{best,last}.pt ; logs -> runs/lewm_*
```
