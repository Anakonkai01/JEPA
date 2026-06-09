"""World-model architectures + the frozen V-JEPA encoder wrapper.

Registry maps a config ``model.name`` string to its class so entrypoints can
build any model from YAML without import-time branching.
"""
from .ac_predictor import ACPredictor
from .leworldmodel import LeWorldModel
from .vjepa2_ac_car import VJEPA2ACCar

# NOTE: ``ACPredictor`` is the POOLED action-conditioned probe (mean-pooled V-JEPA
# latent + 2-token transformer, ~7.4M). It is NOT Meta's V-JEPA 2-AC (that one is
# patch-token, depth-24, action+state, block-causal — see reference/vjepa2). So it is
# registered honestly as a BASELINE; ``vjepa_ac`` is kept as a back-compat alias so
# existing checkpoints (cfg.model.name == "vjepa_ac") still load.
MODEL_REGISTRY = {
    "vjepa_ac_pool": ACPredictor,   # honest name — pooled AC probe (BASELINE)
    "vjepa_ac": ACPredictor,        # alias (back-compat: shipped checkpoints)
    "vjepa_ac_car": VJEPA2ACCar,    # faithful patch-token V-JEPA-2-AC (contribution)
    "leworldmodel": LeWorldModel,
}


def build_model(cfg: dict):
    """Instantiate a model from a ``model`` config dict (must contain ``name``)."""
    name = cfg["name"]
    if name not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model.name={name!r}. Known: {list(MODEL_REGISTRY)}")
    kwargs = {k: v for k, v in cfg.items() if k != "name"}
    return MODEL_REGISTRY[name](**kwargs)


__all__ = ["ACPredictor", "LeWorldModel", "MODEL_REGISTRY", "build_model"]
