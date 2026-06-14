#!/usr/bin/env python3
"""Standalone Flask app (port 8070) for the OPEN-LOOP energy-landscape demo.

Serves web/demo.html + precomputed data/demo/<session>/demo.json + frames. PLAYING needs
NO GPU/PyTorch — demo_precompute.py already did the model work. Optional on-demand
precompute (POST /api/precompute/<session>) shells out to the script (needs GPU, cached after).

    bash run_demo.sh      # or: PYTHONPATH=src ~/miniforge3/envs/ai/bin/python scripts/demo_web.py
Open http://localhost:8070  (or Tailscale IP:8070).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request, send_file

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "data" / "demo"
HTML = ROOT / "web" / "demo.html"
RAW_DIRS = [ROOT / "data" / "raw_towerpro", ROOT / "data" / "raw_kds", ROOT / "data" / "raw_mixed"]
SPLIT = ROOT / "checkpoints" / "vjepa_ac_car_cd4" / "vjepa_ac_car" / "split.json"
PATCH_DIR = ROOT / "data" / "latents_towerpro_patch_384"

app = Flask(__name__)


def _raw_dir(session: str):
    for d in RAW_DIRS:
        if (d / session / "frames").is_dir():
            return d / session
    return None


def _rank_val():
    """Ranked TowerPro VAL sessions (turn-content × length × motion) — pure CSV, no model."""
    try:
        val = set(json.load(open(SPLIT))["val"])
    except Exception:
        val = set()
    patch = {p.stem for p in PATCH_DIR.glob("*.npy")}
    out = []
    for s in sorted(val & patch):
        rd = _raw_dir(s)
        f = rd / "actions_synced.csv" if rd else None
        if not f or not f.exists():
            continue
        rr = list(csv.DictReader(open(f)))
        st = np.array([float(r["steering"]) for r in rr])
        th = np.array([float(r["throttle"]) for r in rr])
        n = len(st)
        if n < 60:
            continue
        pct_turn = float(np.mean(np.abs(st) > 0.15))
        pct_move = float(np.mean(np.abs(th) > 0.04))
        out.append({"session": s, "n": n, "pct_turn": round(pct_turn, 3),
                    "pct_move": round(pct_move, 3),
                    "score": round(pct_turn * min(n, 400) * max(pct_move, 0.05), 1)})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


@app.route("/")
def index():
    return send_file(HTML)


@app.route("/api/sessions")
def api_sessions():
    ready = {p.parent.name for p in DEMO_DIR.glob("*/demo.json")}
    ranked = _rank_val()
    for r in ranked:
        r["ready"] = r["session"] in ready
    known = {r["session"] for r in ranked}
    extra = [{"session": s, "ready": True, "n": None, "pct_turn": None}
             for s in sorted(ready) if s not in known]
    return jsonify({"ranked": ranked, "extra": extra})


@app.route("/api/demo/<session>")
def api_demo(session):
    p = DEMO_DIR / session / "demo.json"
    if not p.exists():
        return jsonify({"error": "chưa precompute session này"}), 404
    return send_file(p, mimetype="application/json")


@app.route("/api/frame/<session>/<int:frame>")
def api_frame(session, frame):
    rd = _raw_dir(session)
    if rd is None:
        return jsonify({"error": "no raw dir"}), 404
    p = rd / "frames" / f"{frame:06d}.jpg"
    if not p.exists():
        return jsonify({"error": f"missing {p.name}"}), 404
    return send_file(p, mimetype="image/jpeg", max_age=86400)


@app.route("/api/precompute/<session>", methods=["POST"])
def api_precompute(session):
    if (DEMO_DIR / session / "demo.json").exists():
        return jsonify({"ok": True, "cached": True})
    d = request.args.get("d", "4")
    cmd = [sys.executable, str(ROOT / "scripts" / "demo_precompute.py"), session, "-d", d]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "precompute timeout"}), 500
    if r.returncode != 0 or not (DEMO_DIR / session / "demo.json").exists():
        return jsonify({"ok": False, "error": (r.stderr or r.stdout)[-1000:]}), 500
    return jsonify({"ok": True, "log": r.stdout[-400:]})


@app.route("/api/export/<session>", methods=["POST"])
def api_export(session):
    if not (DEMO_DIR / session / "demo.json").exists():
        return jsonify({"ok": False, "error": "chưa precompute session này"}), 404
    out = DEMO_DIR / session / f"{session}.mp4"
    cmd = [sys.executable, str(ROOT / "scripts" / "demo_export_mp4.py"), session]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "export timeout"}), 500
    if r.returncode != 0 or not out.exists():
        return jsonify({"ok": False, "error": (r.stderr or r.stdout)[-1000:]}), 500
    return jsonify({"ok": True, "url": f"/api/mp4/{session}"})


@app.route("/api/mp4/<session>")
def api_mp4(session):
    p = DEMO_DIR / session / f"{session}.mp4"
    if not p.exists():
        return jsonify({"error": "chưa export"}), 404
    return send_file(p, mimetype="video/mp4", as_attachment=True, download_name=f"demo_{session}.mp4")


if __name__ == "__main__":
    print("[demo_web] http://0.0.0.0:8070  (precomputed sessions:",
          ", ".join(sorted(p.parent.name for p in DEMO_DIR.glob("*/demo.json"))) or "none", ")")
    app.run(host="0.0.0.0", port=8070, threaded=True)
