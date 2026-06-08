"""Topological graph over V-JEPA latents for visual subgoal navigation.

Nodes = recorded frames (subsampled), each carrying its L2-normalized V-JEPA
latent (visual place), GPS in local metres, and travel heading. Edges:

  * temporal     — consecutive nodes within one session ("the human drove this",
                   so it is traversable), weight = metres between them.
  * loop-closure — k-NN in latent space across *different* sessions, kept only
                   when GPS agrees (``gps_dist < gps_gate_m``) so perceptual
                   aliasing (two look-alike spots far apart) is rejected. These
                   are "same physical place seen twice" links, weight ~0.

Routing is Dijkstra over edge metres; ``extract_subgoals`` turns a node path into
a sequence of frame images ~``spacing_m`` apart for a local CEM controller.

The layer is action-agnostic (place + GPS only), so it mixes servo domains
(KDS + TowerPro) freely. Build via ``build_topograph`` / ``scripts/build_graph.py``.
"""
from __future__ import annotations

import csv
import heapq
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

# Local-tangent-plane metres per degree near the park (lat ~10.68N).
_MLAT = 110540.0


def _m_per_deg_lon(lat0: float) -> float:
    return 111320.0 * math.cos(math.radians(lat0))


def _read_gps(path: Path):
    """Return (t_ms, lat, lon, speed) arrays, dropping null fixes."""
    t, la, lo, sp = [], [], [], []
    if not path.exists():
        return (np.array([]),) * 4
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                a, b = float(r["lat"]), float(r["lon"])
                if a == 0 or b == 0:
                    continue
                t.append(float(r["t_ms"])); la.append(a); lo.append(b)
                sp.append(float(r.get("speed", 0) or 0))
            except (ValueError, KeyError):
                continue
    return np.array(t), np.array(la), np.array(lo), np.array(sp)


def _gps_implausible(gt, gla, glo, max_extent_m: float, max_speed: float) -> bool:
    """True if a session's GPS track is physically impossible (drift / lost lock):
    extent bigger than the venue, or an inter-fix speed no RC car could do."""
    if len(gt) < 3:
        return True
    lat0 = float(gla.mean())
    x = (glo - glo.mean()) * _m_per_deg_lon(lat0)
    y = (gla - gla.mean()) * _MLAT
    extent = math.hypot(float(x.max() - x.min()), float(y.max() - y.min()))
    d = np.hypot(np.diff(x), np.diff(y))
    dt = np.clip(np.diff(gt) / 1000.0, 0.05, None)
    vmax = float((d / dt).max())
    return extent > max_extent_m or vmax > max_speed


def _read_synced_times(path: Path) -> dict[int, float]:
    """frame_idx -> t_scene_ms from actions_synced.csv."""
    out: dict[int, float] = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out[int(r["frame_idx"])] = float(r["t_scene_ms"])
    return out


@dataclass
class _RootSpec:
    latents: Path
    raw: Path
    domain: str


def _resolve_roots(roots) -> list[_RootSpec]:
    specs = []
    for r in roots:
        specs.append(_RootSpec(Path(r["latents"]), Path(r["raw"]),
                               str(r.get("domain") or Path(r["raw"]).name)))
    return specs


class TopoGraph:
    """In-memory topological map; build with :func:`build_topograph`."""

    def __init__(self, *, Zn, XY, latlon, heading, node_root, node_session,
                 node_frame, suid, edges, origin, roots, params):
        self.Zn = Zn                      # (M, D) float32, L2-normalized
        self.XY = XY                      # (M, 2) float32 metres
        self.latlon = latlon              # (M, 2) float64
        self.heading = heading            # (M,) float32 radians
        self.node_root = node_root        # (M,) int  -> roots[node_root[i]]
        self.node_session = node_session  # (M,) object str (basename)
        self.node_frame = node_frame      # (M,) int  (jpg index)
        self.suid = suid                  # (M,) int  unique (root,session) id
        self.edges = edges                # (E, 3): src, dst, weight
        self.origin = origin              # (lat0, lon0)
        self.roots = roots                # list[_RootSpec]
        self.params = params              # build params dict
        self._build_adj()

    # ---- adjacency ----------------------------------------------------
    def _build_adj(self):
        M = len(self.Zn)
        self.adj: list[list[tuple[int, float]]] = [[] for _ in range(M)]
        for s, d, w in self.edges:
            s, d = int(s), int(d)
            self.adj[s].append((d, float(w)))
            self.adj[d].append((s, float(w)))

    # ---- persistence --------------------------------------------------
    def save(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "Zn": self.Zn, "XY": self.XY, "latlon": self.latlon,
            "heading": self.heading, "node_root": self.node_root,
            "node_session": np.asarray(self.node_session, dtype=object),
            "node_frame": self.node_frame, "suid": self.suid,
            "edges": self.edges, "origin": self.origin,
            "roots": [{"latents": str(r.latents), "raw": str(r.raw), "domain": r.domain}
                      for r in self.roots],
            "params": self.params,
        }, path)

    @classmethod
    def load(cls, path):
        d = torch.load(path, weights_only=False)
        return cls(
            Zn=d["Zn"], XY=d["XY"], latlon=d["latlon"], heading=d["heading"],
            node_root=d["node_root"], node_session=d["node_session"],
            node_frame=d["node_frame"], suid=d["suid"], edges=d["edges"],
            origin=d["origin"], roots=_resolve_roots(d["roots"]), params=d["params"],
        )

    # ---- geometry helpers --------------------------------------------
    def to_xy(self, lat, lon):
        lat0, lon0 = self.origin
        return np.array([(lon - lon0) * _m_per_deg_lon(lat0), (lat - lat0) * _MLAT],
                        dtype=np.float32)

    def frame_path(self, node: int) -> Path:
        r = self.roots[int(self.node_root[node])]
        return r.raw / str(self.node_session[node]) / "frames" / f"{int(self.node_frame[node]):06d}.jpg"

    # ---- localization -------------------------------------------------
    def localize(self, latent, gps_prior=None, gate_m: float = 15.0, blocked=None) -> int:
        """Nearest node by cosine; if a (lat,lon) prior is given, restrict to
        nodes within ``gate_m`` (falls back to global if none qualify). ``blocked``
        (iterable of node ids) are excluded — used for leave-one-session-out."""
        q = np.asarray(latent, dtype=np.float32).reshape(-1)
        q = q / (np.linalg.norm(q) + 1e-8)
        sims = self.Zn @ q
        if gps_prior is not None:
            xy = self.to_xy(*gps_prior)
            d = np.linalg.norm(self.XY - xy, axis=1)
            mask = d < gate_m
            if mask.any():
                sims = np.where(mask, sims, -2.0)
        if blocked is not None:
            sims[list(blocked)] = -2.0
        return int(np.argmax(sims))

    # ---- routing ------------------------------------------------------
    def plan_route(self, start: int, goal: int, blocked=None) -> list[int] | None:
        """Dijkstra over edge metres -> list of node ids, or None if disjoint.
        ``blocked`` node ids are skipped (leave-one-session-out routing)."""
        M = len(self.Zn)
        block = set(int(b) for b in blocked) if blocked is not None else set()
        dist = [math.inf] * M
        prev = [-1] * M
        dist[start] = 0.0
        pq = [(0.0, start)]
        while pq:
            du, u = heapq.heappop(pq)
            if u == goal:
                break
            if du > dist[u]:
                continue
            for v, w in self.adj[u]:
                if v in block:
                    continue
                nd = du + w
                if nd < dist[v]:
                    dist[v] = nd; prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if not math.isfinite(dist[goal]):
            return None
        path = []
        u = goal
        while u != -1:
            path.append(u); u = prev[u]
        return path[::-1]

    def extract_subgoals(self, path: list[int], spacing_m: float = 4.0) -> list[int]:
        """Downsample a node path to subgoal nodes ~spacing_m apart (plus the
        node at each session switch, and always the final goal)."""
        if not path:
            return []
        subs = [path[0]]
        acc = 0.0
        for a, b in zip(path[:-1], path[1:]):
            acc += float(np.linalg.norm(self.XY[b] - self.XY[a]))
            switch = self.suid[a] != self.suid[b]
            if acc >= spacing_m or switch:
                subs.append(b); acc = 0.0
        if subs[-1] != path[-1]:
            subs.append(path[-1])
        return subs

    # ---- introspection ------------------------------------------------
    def components(self) -> list[list[int]]:
        M = len(self.Zn); seen = np.zeros(M, bool); comps = []
        for s0 in range(M):
            if seen[s0]:
                continue
            stack = [s0]; seen[s0] = True; comp = []
            while stack:
                u = stack.pop(); comp.append(u)
                for v, _ in self.adj[u]:
                    if not seen[v]:
                        seen[v] = True; stack.append(v)
            comps.append(comp)
        return sorted(comps, key=len, reverse=True)


# ======================================================================
# Builder
# ======================================================================
def build_topograph(roots, *, node_stride: int = 5, knn: int = 8,
                    gps_gate_m: float = 8.0, sim_min: float = 0.5,
                    loop_weight: float = 0.5, max_jump_m: float = 15.0,
                    max_gps_extent_m: float = 160.0, max_gps_speed: float = 12.0,
                    chunk: int = 2048, verbose: bool = True) -> TopoGraph:
    """Build a :class:`TopoGraph` from one or more (latents, raw) roots.

    Args:
        roots: list of ``{"latents": dir, "raw": dir, "domain": name}``.
        node_stride: keep every Nth synced frame as a node (~0.5s at stride 5).
        knn: max loop-closure edges per node.
        gps_gate_m: reject a loop-closure if the two nodes' GPS differ by more.
        sim_min: minimum cosine for a loop-closure candidate.
        loop_weight: metres assigned to a loop-closure edge (same place ~= 0).
        max_jump_m: drop a node whose GPS is > this from BOTH temporal neighbours
            (isolated spike = impossible teleport at ~0.5s/node). 0 disables.
    """
    specs = _resolve_roots(roots)

    Z, LL, ROOT, SESS, FR = [], [], [], [], []
    for ri, sp in enumerate(specs):
        sessions = sorted(p.name for p in sp.raw.glob("session_*")
                          if (p / "actions_synced.csv").exists()
                          and (sp.latents / f"{p.name}.pt").exists())
        for sess in sessions:
            d = torch.load(sp.latents / f"{sess}.pt", weights_only=False)
            lat = d["latents"].numpy().astype(np.float32)
            fidx = d["frame_idx"].numpy()
            times = _read_synced_times(sp.raw / sess / "actions_synced.csv")
            gt, gla, glo, _ = _read_gps(sp.raw / sess / "gps.csv")
            if len(gt) < 3:
                continue
            if _gps_implausible(gt, gla, glo, max_gps_extent_m, max_gps_speed):
                if verbose:
                    print(f"[graph] skip {sess}: GPS drift/lost-lock", flush=True)
                continue
            keep = np.arange(0, len(lat), node_stride)
            for i in keep:
                fi = int(fidx[i])
                t = times.get(fi)
                if t is None:
                    continue
                la = float(np.interp(t, gt, gla)); lo = float(np.interp(t, gt, glo))
                Z.append(lat[i]); LL.append((la, lo))
                ROOT.append(ri); SESS.append(sess); FR.append(fi)
        if verbose:
            print(f"[graph] root {sp.domain}: {len(Z)} nodes so far", flush=True)

    Z = np.asarray(Z, dtype=np.float32)
    LL = np.asarray(LL, dtype=np.float64)
    ROOT = np.asarray(ROOT, dtype=np.int32)
    SESS = np.asarray(SESS, dtype=object)
    FR = np.asarray(FR, dtype=np.int64)
    M = len(Z)
    if M == 0:
        raise RuntimeError("No nodes built — check latents/raw dirs and gps.csv presence.")

    # local metres
    lat0 = float(LL[:, 0].mean()); lon0 = float(LL[:, 1].mean())
    mlon = _m_per_deg_lon(lat0)
    XY = np.stack([(LL[:, 1] - lon0) * mlon, (LL[:, 0] - lat0) * _MLAT], axis=1).astype(np.float32)

    # unique (root, session) id + ordering within session
    suid = np.empty(M, dtype=np.int64)
    key2uid: dict[tuple[int, str], int] = {}
    for i in range(M):
        k = (int(ROOT[i]), str(SESS[i]))
        suid[i] = key2uid.setdefault(k, len(key2uid))

    # drop GPS spikes: a node far from BOTH temporal neighbours can't be real
    if max_jump_m and max_jump_m > 0:
        keep = np.ones(M, dtype=bool)
        for u in np.unique(suid):
            ids = np.where(suid == u)[0]        # frame order
            for j in range(len(ids)):
                i = ids[j]
                nbr = []
                if j > 0:
                    nbr.append(np.linalg.norm(XY[i] - XY[ids[j - 1]]))
                if j < len(ids) - 1:
                    nbr.append(np.linalg.norm(XY[i] - XY[ids[j + 1]]))
                if nbr and min(nbr) > max_jump_m:
                    keep[i] = False
        n_drop = int((~keep).sum())
        if n_drop:
            Z, LL, XY = Z[keep], LL[keep], XY[keep]
            ROOT, SESS, FR, suid = ROOT[keep], SESS[keep], FR[keep], suid[keep]
            M = len(Z)
            if verbose:
                print(f"[graph] dropped {n_drop} GPS-spike nodes -> {M} nodes", flush=True)

    # heading from travel direction within a session (avoids GPS-bearing wrap)
    heading = np.zeros(M, dtype=np.float32)
    for u in np.unique(suid):
        ids = np.where(suid == u)[0]            # already in frame order
        for j in range(len(ids)):
            a = ids[j]; b = ids[min(j + 1, len(ids) - 1)]
            dx, dy = XY[b] - XY[a]
            heading[a] = math.atan2(dy, dx) if (dx or dy) else (heading[ids[j - 1]] if j else 0.0)

    Zn = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-8)

    # ---- temporal edges ----
    edges = []
    for u in np.unique(suid):
        ids = np.where(suid == u)[0]
        for a, b in zip(ids[:-1], ids[1:]):
            w = float(np.linalg.norm(XY[b] - XY[a]))
            edges.append((int(a), int(b), w))
    n_temporal = len(edges)

    # ---- loop-closure edges (chunked k-NN, GPS-gated) ----
    n_loop = 0; n_alias = 0
    for s in range(0, M, chunk):
        e = min(s + chunk, M)
        sims = Zn[s:e] @ Zn.T                    # (chunk, M)
        # consider a generous candidate pool, then gate
        cand = np.argsort(-sims, axis=1)[:, 1:60]
        for r in range(e - s):
            i = s + r
            cnt = 0
            for j in cand[r]:
                j = int(j)
                if suid[j] == suid[i]:
                    continue
                if sims[r, j] < sim_min:
                    break
                dij = float(np.linalg.norm(XY[i] - XY[j]))
                if dij < gps_gate_m:
                    edges.append((i, j, loop_weight)); n_loop += 1; cnt += 1
                    if cnt >= knn:
                        break
                else:
                    n_alias += 1
        if verbose:
            print(f"[graph] loop-closure {e}/{M} (edges={n_loop}, alias_rejected={n_alias})", flush=True)

    edges = np.asarray(edges, dtype=np.float64)
    params = {"node_stride": node_stride, "knn": knn, "gps_gate_m": gps_gate_m,
              "sim_min": sim_min, "loop_weight": loop_weight,
              "n_temporal": n_temporal, "n_loop": n_loop, "n_alias_rejected": n_alias}
    if verbose:
        print(f"[graph] DONE: {M} nodes | {n_temporal} temporal + {n_loop} loop edges "
              f"| {n_alias} alias rejected", flush=True)
    return TopoGraph(Zn=Zn, XY=XY, latlon=LL, heading=heading, node_root=ROOT,
                     node_session=SESS, node_frame=FR, suid=suid, edges=edges,
                     origin=(lat0, lon0), roots=specs, params=params)
