"""Lightweight YAML config loading with CLI overrides (no Hydra dependency).

Usage in an entrypoint::

    from jepa_wm.utils import load_config, merge_overrides
    cfg = load_config("configs/train/default.yaml", "configs/model/vjepa_ac.yaml")
    cfg = merge_overrides(cfg, ["train.lr=3e-4", "train.epochs=80"])

Configs are plain dicts. Multiple files are deep-merged left-to-right (later wins).
Dotted CLI overrides (``a.b.c=value``) are parsed with a YAML scalar loader so
numbers/bools/null come through with the right type.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable

import yaml


def _deep_merge(base: dict, other: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in other.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(*paths: str | Path) -> dict:
    """Load and deep-merge one or more YAML config files (later files win)."""
    cfg: dict[str, Any] = {}
    for p in paths:
        with open(p, "r") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config {p} must be a mapping, got {type(loaded)}")
        cfg = _deep_merge(cfg, loaded)
    return cfg


def merge_overrides(cfg: dict, overrides: Iterable[str]) -> dict:
    """Apply dotted ``key.path=value`` overrides (value parsed as a YAML scalar)."""
    cfg = copy.deepcopy(cfg)
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"Override must be key=value, got: {item!r}")
        key, raw = item.split("=", 1)
        value = yaml.safe_load(raw)
        node = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return cfg
