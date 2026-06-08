"""Datasets for the world models.

- ``FrameSequenceDataset``   : sub-trajectories of (pixels, actions) for LeWM
  (end-to-end pixel JEPA). Reads recorded sessions directly.
- ``LatentTransitionDataset``: windows of pre-encoded V-JEPA latents for the
  frozen-encoder AC predictor (vjepa_ac) — depends on engine.encode (TODO).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset


@dataclass(frozen=True)
class DataRoot:
    """One synced recording root, optionally tagged with a servo/domain name."""

    path: Path
    domain: str
    domain_id: int


def _safe_domain(path: Path) -> str:
    name = path.name.replace("raw_", "").replace("raw", "default")
    return name or "default"


def normalize_roots(raw_dir: str | Path | Iterable[Any]) -> list[DataRoot]:
    """Normalize old ``raw_dir`` and new multi-root config shapes.

    Accepted forms:
      - ``"data/raw_towerpro"``
      - ``["data/raw", "data/raw_towerpro"]``
      - ``[{"path": "data/raw", "domain": "kds"}, ...]``
    """
    if isinstance(raw_dir, (str, Path)):
        path = Path(raw_dir)
        return [DataRoot(path=path, domain=_safe_domain(path), domain_id=0)]

    roots: list[DataRoot] = []
    for i, item in enumerate(raw_dir):
        if isinstance(item, (str, Path)):
            path = Path(item)
            roots.append(DataRoot(path=path, domain=_safe_domain(path), domain_id=i))
            continue
        if not isinstance(item, dict):
            raise TypeError(f"raw_dir entries must be path-like or dicts, got {type(item)}")
        path = Path(item["path"])
        domain = str(item.get("domain") or _safe_domain(path))
        domain_id = int(item.get("domain_id", i))
        roots.append(DataRoot(path=path, domain=domain, domain_id=domain_id))
    if not roots:
        raise ValueError("No dataset roots configured")
    return roots


def list_sessions(raw_dir: str | Path | Iterable[Any]) -> list[str]:
    roots = normalize_roots(raw_dir)
    multi = len(roots) > 1
    out: list[str] = []
    for root in roots:
        names = sorted(p.name for p in root.path.glob("session_*")
                       if (p / "actions_synced.csv").exists())
        out.extend(f"{root.domain}:{s}" if multi else s for s in names)
    return sorted(out)


def split_sessions(sessions: list[str], val_frac: float = 0.2, seed: int = 0):
    """Deterministic session-level train/val split."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(sessions))
    n_val = max(1, round(len(sessions) * val_frac))
    val_idx = set(order[:n_val].tolist())
    train = [s for i, s in enumerate(sessions) if i not in val_idx]
    val = [s for i, s in enumerate(sessions) if i in val_idx]
    return train, val


class FrameSequenceDataset(Dataset):
    """Sliding sub-trajectories of frames + per-frame actions from synced sessions.

    Each item: ``pixels (T, 3, H, W)`` in [-1, 1], ``actions (T, A)``.
    Action ``a_t`` is the synced command at frame ``t`` (used to predict frame t+1).

    Args:
        raw_dir:     dir or list of dirs containing synced ``session_*/`` recordings.
        sessions:    explicit session names/ids (default: all synced under raw_dir).
        seq_len:     frames per sub-trajectory (T).
        frame_skip:  stride between frames *within* a window (>1 = more motion/window).
        stride:      step between consecutive window starts (overlap control).
        image_size:  square resize.
        action_keys: action columns to stack.
        action_scale: per-action multiplier applied after loading/interpolation.
        action_aggregation:
            ``sample`` keeps the command exactly at sampled frames.
            ``block_mean`` averages rows from sampled frame k up to k+frame_skip,
            so a skip-5 transition is conditioned on all commands in that block.
        domain_token:
            ``none``/false leaves actions unchanged.
            ``scalar`` appends one scalar domain token in [-1, 1].
            ``onehot`` appends a one-hot domain vector.
    """

    def __init__(
        self,
        raw_dir: str | Path,
        sessions: list[str] | None = None,
        seq_len: int = 4,
        frame_skip: int = 1,
        stride: int = 2,
        image_size: int = 224,
        action_keys: tuple[str, ...] = ("steering", "throttle"),
        action_scale: tuple[float, ...] | list[float] | None = None,
        action_aggregation: str = "sample",
        domain_token: str | bool | None = "none",
    ):
        self.roots = normalize_roots(raw_dir)
        self._root_by_domain = {r.domain: r for r in self.roots}
        self._session_lookup: dict[str, list[DataRoot]] = {}
        for root in self.roots:
            for p in root.path.glob("session_*"):
                if (p / "actions_synced.csv").exists():
                    self._session_lookup.setdefault(p.name, []).append(root)
        self.seq_len = seq_len
        self.frame_skip = frame_skip
        self.image_size = image_size
        self.action_keys = tuple(action_keys)
        self.action_scale = np.asarray(action_scale or [1.0] * len(self.action_keys), dtype=np.float32)
        if len(self.action_scale) != len(self.action_keys):
            raise ValueError("action_scale length must match action_keys")
        if action_aggregation not in {"sample", "block_mean"}:
            raise ValueError("action_aggregation must be 'sample' or 'block_mean'")
        self.action_aggregation = action_aggregation
        if domain_token is True:
            domain_token = "scalar"
        if domain_token in (False, None):
            domain_token = "none"
        if domain_token not in {"none", "scalar", "onehot"}:
            raise ValueError("domain_token must be none/scalar/onehot")
        self.domain_token = str(domain_token)
        self.domain_count = max(r.domain_id for r in self.roots) + 1
        self.sessions = sessions if sessions is not None else list_sessions(raw_dir)

        self._rows: dict[str, dict] = {}     # session id -> row/frame/action metadata
        self._index: list[tuple[str, int]] = []  # (session id, start position in rows)
        span = (seq_len - 1) * frame_skip
        for s in self.sessions:
            root, session, sid = self._resolve_session(s)
            fidx, acts = self._read_session(root, session)
            if len(fidx) <= span:
                continue
            self._rows[sid] = {
                "root": root.path, "session": session, "fidx": fidx, "acts": acts,
                "domain_id": root.domain_id,
            }
            for start in range(0, len(fidx) - span, stride):
                self._index.append((sid, start))

    def _resolve_session(self, session_id: str) -> tuple[DataRoot, str, str]:
        if ":" in session_id:
            domain, session = session_id.split(":", 1)
            root = self._root_by_domain.get(domain)
            if root is None:
                raise KeyError(f"Unknown dataset domain {domain!r} for session {session_id!r}")
            return root, session, session_id

        roots = self._session_lookup.get(session_id, [])
        if len(roots) == 1:
            sid = session_id if len(self.roots) == 1 else f"{roots[0].domain}:{session_id}"
            return roots[0], session_id, sid
        if not roots:
            raise FileNotFoundError(f"Session {session_id!r} was not found in configured roots")
        domains = ", ".join(r.domain for r in roots)
        raise ValueError(f"Ambiguous session {session_id!r}; prefix one of: {domains}")

    def _read_session(self, root: DataRoot, session: str):
        path = root.path / session / "actions_synced.csv"
        fidx, acts = [], []
        with open(path) as f:
            for row in csv.DictReader(f):
                fidx.append(int(row["frame_idx"]))
                acts.append([float(row[k]) for k in self.action_keys])
        arr = np.asarray(acts, dtype=np.float32)
        arr *= self.action_scale[None, :]
        return fidx, arr

    def __len__(self) -> int:
        return len(self._index)

    def _load_frame(self, root: Path, session: str, frame_idx: int) -> torch.Tensor:
        p = root / session / "frames" / f"{frame_idx:06d}.jpg"
        img = Image.open(p).convert("RGB").resize((self.image_size, self.image_size), Image.BILINEAR)
        arr = torch.from_numpy(np.asarray(img, dtype=np.float32)).permute(2, 0, 1) / 255.0
        return arr.mul_(2.0).sub_(1.0)        # [-1, 1]

    def _domain_features(self, domain_id: int, n: int) -> np.ndarray:
        if self.domain_token == "none":
            return np.empty((n, 0), dtype=np.float32)
        if self.domain_token == "scalar":
            val = 0.0 if self.domain_count <= 1 else -1.0 + 2.0 * domain_id / (self.domain_count - 1)
            return np.full((n, 1), val, dtype=np.float32)
        out = np.zeros((n, self.domain_count), dtype=np.float32)
        out[:, domain_id] = 1.0
        return out

    def _actions_for_positions(self, acts: np.ndarray, positions: list[int]) -> np.ndarray:
        if self.action_aggregation == "sample" or self.frame_skip == 1:
            return acts[positions]
        out = []
        n = len(acts)
        for p in positions:
            end = min(n, p + self.frame_skip)
            out.append(acts[p:end].mean(axis=0))
        return np.asarray(out, dtype=np.float32)

    def __getitem__(self, i: int):
        sid, start = self._index[i]
        rec = self._rows[sid]
        positions = [start + k * self.frame_skip for k in range(self.seq_len)]
        pixels = torch.stack([self._load_frame(rec["root"], rec["session"], rec["fidx"][p]) for p in positions])
        actions_np = self._actions_for_positions(rec["acts"], positions)
        domain_np = self._domain_features(rec["domain_id"], len(positions))
        actions = torch.from_numpy(np.concatenate([actions_np, domain_np], axis=1))
        return {"pixels": pixels, "actions": actions}


class LatentTransitionDataset(Dataset):
    """Windows of pre-encoded V-JEPA latents + actions for the AC predictor (vjepa_ac).

    Reads per-session ``data/latents/<session>.pt`` (written by engine.encode):
        {"latents": FloatTensor (N, D), "frame_idx": LongTensor (N,)}
    where row i is aligned 1:1 with row i of that session's ``actions_synced.csv``
    (same order, same scene-time). A sample is a window of ``horizon`` action steps::

        s_{t .. t+H}   latents  (H+1, D)
        a_{t .. t+H-1} actions  (H,  A)

    For the single-step ACPredictor use horizon=1 -> (s_t, a_t, s_{t+1}).
    Windows never cross a session boundary or a non-contiguous frame gap.
    """

    def __init__(self, latents_dir, raw_dir="data/raw", sessions=None, horizon=1,
                 action_keys=("steering", "throttle"), action_scale=None, max_gap=2):
        self.latents_dir = Path(latents_dir)
        self.raw = Path(raw_dir)
        self.horizon = horizon
        self.action_keys = tuple(action_keys)
        # per-dim multiplier so e.g. throttle (~[-0.16,0.15]) gets the same voice
        # as steering (~[-1,1]); raw throttle is ~6.67x smaller and gets under-weighted.
        self.action_scale = np.asarray(action_scale or [1.0] * len(self.action_keys), dtype=np.float32)
        if len(self.action_scale) != len(self.action_keys):
            raise ValueError("action_scale length must match action_keys")
        if sessions is None:
            sessions = sorted(p.stem for p in self.latents_dir.glob("*.pt"))
        self._lat: dict[str, torch.Tensor] = {}
        self._act: dict[str, np.ndarray] = {}
        self._index: list[tuple[str, int]] = []
        for s in sessions:
            lp = self.latents_dir / f"{s}.pt"
            ap = self.raw / s / "actions_synced.csv"
            if not lp.exists() or not ap.exists():
                continue
            blob = torch.load(lp, map_location="cpu")
            lat, fidx = blob["latents"].float(), list(blob["frame_idx"])
            acts, csv_fidx = self._read_actions(ap)
            n = min(len(fidx), len(csv_fidx))
            assert fidx[:n] == csv_fidx[:n], f"latent/action frame_idx mismatch in {s}"
            self._lat[s] = lat[:n]
            self._act[s] = acts[:n]
            fset = fidx[:n]
            for t in range(n - horizon):
                # require contiguous frames across the window (no telemetry-gap holes)
                if fset[t + horizon] - fset[t] <= horizon * max_gap:
                    self._index.append((s, t))

    def _read_actions(self, path):
        acts, fidx = [], []
        with open(path) as f:
            for row in csv.DictReader(f):
                fidx.append(int(row["frame_idx"]))
                acts.append([float(row[k]) for k in self.action_keys])
        arr = np.asarray(acts, dtype=np.float32)
        if len(arr):
            arr *= self.action_scale[None, :]
        return arr, fidx

    def __len__(self):
        return len(self._index)

    def __getitem__(self, i):
        s, t = self._index[i]
        H = self.horizon
        latents = self._lat[s][t:t + H + 1]                    # (H+1, D)
        actions = torch.from_numpy(self._act[s][t:t + H])      # (H, A)
        if H == 1:
            return {"s_t": latents[0], "a_t": actions[0], "s_next": latents[1]}
        return {"latents": latents, "actions": actions}
