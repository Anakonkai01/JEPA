"""jepa_wm — Action-Conditioned World Model for RC-car navigation.

Two predictors share one frozen V-JEPA 2.1 encoder and one latent dataset:
  - models.ac_predictor.ACPredictor   ("v-jepa-2.1-ac", the main contribution)
  - models.leworldmodel.LeWorldModel  (recurrent latent baseline)

Pipeline:  raw session (robot/) -> data.sync -> engine.encode (latents) -> engine.train.

See README.md and docs/PLAN.md.
"""

__version__ = "0.1.0"
