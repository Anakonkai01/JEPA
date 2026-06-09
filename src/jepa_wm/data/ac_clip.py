"""ACClipDataset — clip windows of (patch tokens, state, action) for VJEPA2ACCar.

Each item is a length-``horizon`` clip sampled at ``frame_stride`` rows (≈ V-JEPA 2-AC's
4 fps: our ~9 fps × stride 2 ≈ 220 ms/step, so consecutive steps differ enough that the
predictor can't cheat with identity — the LeWM frame_skip lesson).

  item = { "tokens":  (T, N, D) float32   patch maps (z-scored by lat_mean/std),
           "states":  (T, S) float32      [speed, yaw_rate, …] (z-scored),
           "actions": (T, A) float32      [steer, throttle] × action_scale }

Targets are implicit: train with L1 on pred[:, :-1] vs tokens[:, 1:] (next-frame).
Patch caches are big (~0.5 MB/frame), so session tensors are loaded lazily with a small
LRU cache rather than all held in RAM.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, Sampler

from jepa_wm.data.state import DEFAULT_COLUMNS, load_state


class SessionBatchSampler(Sampler):
    """Yield batches whose items all come from ONE session, with session order +
    within-session windows shuffled each epoch. Keeps the per-session token cache
    (``_load_tokens`` LRU) hot — random global shuffling would reload a ~500 MB session
    tensor every batch (disk-bound). Randomness: SGD sees sessions in random order and
    windows shuffled within each session.
    """

    def __init__(self, index, batch_size, shuffle=True, drop_last=True, seed=0):
        self.bs = batch_size; self.shuffle = shuffle; self.drop_last = drop_last
        self.seed = seed; self.epoch = 0
        self.by_session = {}
        for pos, (s, _) in enumerate(index):
            self.by_session.setdefault(s, []).append(pos)

    def set_epoch(self, e):
        self.epoch = e

    def __iter__(self):
        g = np.random.default_rng(self.seed + self.epoch)
        sessions = list(self.by_session)
        if self.shuffle:
            g.shuffle(sessions)
        for s in sessions:
            rows = np.array(self.by_session[s])
            if self.shuffle:
                g.shuffle(rows)
            for i in range(0, len(rows), self.bs):
                batch = rows[i:i + self.bs].tolist()
                if self.drop_last and len(batch) < self.bs:
                    continue
                yield batch

    def __len__(self):
        n = 0
        for rows in self.by_session.values():
            n += len(rows) // self.bs if self.drop_last else -(-len(rows) // self.bs)
        return n


def _read_actions(session_dir):
    with open(Path(session_dir) / "actions_synced.csv") as f:
        rows = list(csv.DictReader(f))
    fidx = np.array([int(r["frame_idx"]) for r in rows])
    act = np.array([[float(r["steering"]), float(r["throttle"])] for r in rows], dtype=np.float32)
    return fidx, act


@lru_cache(maxsize=2)
def _load_tokens(npy_path):
    """Memmap the patch cache (no full load) — __getitem__ reads only the rows a window
    needs, so RAM stays tiny even for 4 GB sessions. maxsize=2 is enough because the
    SessionBatchSampler keeps consecutive batches within one session."""
    return np.load(npy_path, mmap_mode="r")           # (N, Ntok, D) fp16 memmap


class ACClipDataset(Dataset):
    def __init__(self, patch_dir, raw_dir, sessions, horizon=4, frame_stride=2,
                 state_columns=DEFAULT_COLUMNS, action_scale=(1.0, 6.67),
                 state_mean=None, state_std=None):
        self.patch_dir = Path(patch_dir); self.raw_dir = Path(raw_dir)
        self.T = horizon; self.stride = frame_stride
        self.cols = tuple(state_columns)
        self.action_scale = torch.tensor(action_scale, dtype=torch.float32)
        self.state_mean, self.state_std = state_mean, state_std

        self.index = []          # (session, start_row)
        self._meta = {}          # session -> (act (N,2), state (N,S), rows, npy_path)
        span = (horizon - 1) * frame_stride
        for s in sessions:
            pt = self.patch_dir / f"{s}.npy"
            if not pt.exists():
                continue
            # Patch cache row order == actions_synced order (encode_patch iterates it) and
            # load_state also derives from actions_synced -> all three align 1:1 by
            # construction. So we DON'T load the (~500 MB) token tensor here, only CSVs.
            fidx, act = _read_actions(self.raw_dir / s)
            state, st_fidx = load_state(self.raw_dir / s, self.cols)
            assert np.array_equal(st_fidx, fidx), f"state/action frame mismatch in {s}"
            rows_in_cache = np.arange(len(fidx))
            self._meta[s] = (act, state, rows_in_cache, str(pt))
            for i in range(len(fidx) - span):
                self.index.append((s, i))

    def __len__(self):
        return len(self.index)

    def __getitem__(self, k):
        s, i = self.index[k]
        act, state, rows_in_cache, pt = self._meta[s]
        local = [i + j * self.stride for j in range(self.T)]      # rows within this session
        cache_rows = rows_in_cache[local]
        arr = _load_tokens(pt)                                    # memmap (N,Ntok,D) fp16
        z = torch.from_numpy(np.ascontiguousarray(arr[cache_rows])).float()  # (T,Ntok,D)
        z = F.layer_norm(z, (z.size(-1),))                       # per-token LN (V-JEPA 2-AC reps)
        st = torch.from_numpy(state[local]).float()              # (T, S)
        a = torch.from_numpy(act[local]).float() * self.action_scale
        if self.state_mean is not None:
            st = (st - self.state_mean) / self.state_std
        return {"tokens": z, "states": st, "actions": a}
