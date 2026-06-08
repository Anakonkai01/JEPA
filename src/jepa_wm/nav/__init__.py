"""Topological visual navigation (graph of subgoal images over V-JEPA latents).

The navigation layer is *action-agnostic*: nodes are recorded frames placed by
their V-JEPA latent (visual place) + GPS, edges are "you can drive here" links
(temporal within a session) and "same place seen twice" links (cross-session
loop-closure, GPS-gated against perceptual aliasing). Routing = shortest path of
subgoal images; a local CEM controller then drives toward each subgoal.

See ``TopoGraph`` and ``scripts/build_graph.py`` / ``scripts/eval_navigation.py``.
"""
from .graph import TopoGraph, build_topograph

__all__ = ["TopoGraph", "build_topograph"]
