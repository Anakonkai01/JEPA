"""World-model architectures + the frozen V-JEPA encoder wrapper.

Registry maps a config ``model.name`` string to its class so entrypoints can
build any model from YAML without import-time branching.
"""
from .ac_predictor import ACPredictor
from .leworldmodel import LeWorldModel

MODEL_REGISTRY = {
    "vjepa_ac": ACPredictor,
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
