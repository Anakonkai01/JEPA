# REPORT IMPROVEMENT — HANDOFF (continue here)

**Created 2026-06-16. This is a self-contained handoff so a fresh Claude (different machine/account)
can continue without the prior chat.** Goal: upgrade `docs/report/2_REPORT_FULL.md` (the main report,
881 lines, currently Vietnamese) to be **professional, complete, image-rich, and in English**.

## Approved decisions (do NOT re-litigate)
1. Keep the report as **polished Markdown** (`.md`); mermaid still renders on GitHub/VS Code.
2. **Translate the ENTIRE report to English** — every heading, paragraph, table cell, caption, and
   mermaid node label — **preserving every number verbatim** and the section order (§1–§18).
   Translate in place in `2_REPORT_FULL.md` (Vietnamese stays in git history).
3. Add **References** (numbered) + insert `[n]` citations at first mention (mainly §2, §5, §10).
4. Add a **List of Figures** and **List of Tables** after the TOC; use stable Fig./Table numbers in
   captions and cross-refs.
5. **Add new figures** (N1–N7 below) + **embed 6 already-rendered orphaned figures** (E1–E6 below).
6. **De-duplicate diagrams**: 4 figures render twice (a PNG *and* an inline ```mermaid block) —
   keep ONE in the body (the PNG), move mermaid/.dot source to Appendix §18 “figure sources”.
7. Fill title-block placeholders (`[Họ tên]`, `[MSSV]`, `[Lớp/Môn]`, `[GVHD]`) — leave clean if unknown.
8. Regenerate **all figures with ENGLISH labels** (scripts + .dot/.mmd already partly edited — see below).

Out of scope unless asked: `3_SLIDES.md`, `4_REPORT_PROSE_FULL.md`.

---

## PROGRESS SO FAR

### ✅ ALL TASKS COMPLETE (2026-06-16) — committed to `main` in 3 commits (625c7af, ab00533, c5fd0bc)

- **Task 1 ✓** — all 7 plot scripts + 10 diagram sources (.dot/.mmd) translated VI→EN; 6 graphviz
  diagrams re-rendered + 7 scripts re-run → 20 PNGs overwritten with English text. (`fig_architecture.dot`
  left untouched — retired/unreferenced, not in the report.)
- **Task 2 ✓** — new figures built (English): N1 `fig_results_summary`, N2 `fig_cross_lighting`,
  N3 `fig_energy_heatmap`, N4 `fig_contrast_vs_horizon`, N5 `fig_frame_montage`, N7 `fig_deploy_loop`
  (+ `src/deploy_loop.dot`). Scripts: `scripts/plot_results_summary|cross_lighting|energy_heatmap|contrast_vs_horizon|frame_montage.py`.
  - **N4 note:** `data/latents/` is pruned on this machine → the GPU contrast-vs-horizon sweep is not
    re-runnable; N4 plots the documented probe_energy steering-contrast anchors (d=2/4/8 = 0.44/0.33/0.27,
    §11.4/§12.1). The d=4 *joint* contrast was cross-checked against demo.json (0.507 ≈ §12.2's 0.52).
- **Task 3 ✓** — `2_REPORT_FULL.md` fully English; embeds E1–E6 + N1–N5,N7; §13 now has 6 figures;
  4 double-rendered diagrams de-duped (PNG in body, mermaid moved to Appendix §18.5); List of Figures
  (1–27) + List of Tables (1–8) added; title block has a clean placeholder line.
- **Task 4 ✓** — numbered References §19 ([1]–[9]) + `[n]` citations at first mention.
- **Task 5 ✓** — verified: 0 Vietnamese-specific chars; 27/27 image links resolve; all `[n]` resolve
  (no orphans); Fig/Table caption numbers match the Lists; key numbers consistent with §18.3.

### ⏳ ONLY REMAINING ITEM — N6 rig photo (needs the user)
§6.1 has a placeholder note for a real photo of the rig (car + onboard phone + ESP32). Ask the user to
supply a photo, save it as `docs/report/figures/fig_rig_photo.jpg`, then replace the placeholder note in
§6.1 with `![Rig](figures/fig_rig_photo.jpg)` + a caption (and add it to the List of Figures as Figure 2,
renumbering the rest, or append as an unnumbered photo to avoid renumbering).

---

## FIGURE PLAN

### Embed these 6 already-rendered PNGs (exist on disk, currently NOT referenced)
| ID | File (in `docs/report/figures/`) | Put into section |
|----|----------------------------------|------------------|
| E1 | `fig_energy_landscape.png` | §11.4 (action-sensitivity) |
| E2 | `fig_trajectory_20260613_171912.png` | §13.1 (run 171912 path vs teach) |
| E3 | `fig_cos_dropout_20260613_171912.png` | §13.2 (cosine collapse trace) |
| E4 | `fig_cos_dropout_mechanism.png` | §13.2 (failure mechanism diagram) |
| E5 | `fig_route_graph.png` | §13.1 (teach route + subgoals) |
| E6 | `fig_data_steer_throttle_2d.png` | §7.2 (joint action distribution) |

**§13 (closed-loop) currently has ZERO figures — this is the biggest visual gap. Fix it with E2–E5 + N2.**
Retire `fig_architecture.png` (older duplicate of `fig_arch_ours.png`, unreferenced).

### New figures to build (Task 2). Effort: CPU=quick, GPU=needs checkpoint+latents, photo=user.
| # | Output PNG | What / why | Source data | Effort | Section |
|---|-----------|-----------|-------------|--------|---------|
| N1 | `fig_results_summary.png` | 3-tier scorecard: Tier-1 rollout 0.744/0.703/0.697 + transfer 1.073→0.975→0.65; Tier-2 sign-turn 94.2%, \|Δsteer\| 0.118, \|Δthr\| 0.033; Tier-3 0/10 + root cause. Up-front “whole story in 5s”. | numbers in report | CPU | §1 or §11 intro |
| N2 | `fig_cross_lighting.png` | Bar chart 66% (same session, near time) vs **0%** (different lighting) of ticks with cos>0.3. The key §13.2 evidence, currently text-only. | `logs/infer_20260613_*.log` | CPU | §13.2 |
| N3 | `fig_energy_heatmap.png` | One frame’s 15×9 `E(steer,throttle)` heatmap with ●human vs ✕model. Makes Tier-2 joint planner tangible. | `data/demo/*/demo.json` field `E2` (joint), `grid`=15 steer, `grid_thr`=9 throttle | CPU | §12 |
| N4 | `fig_contrast_vs_horizon.png` | Line plot contrast vs horizon d=2..8 (≈0.44→0.27) justifying d=4. | `scripts/probe_energy.py` sweep | GPU | §11/§12 |
| N5 | `fig_frame_montage.png` | 6–8 representative onboard frames (varied light/time) — shows what the encoder sees. | `data/raw_*/*/frames` | CPU | §6 or §7 |
| N6 | (user photo) | Real rig photo (car + phone + ESP32). **DEFERRED — ask user to supply.** | user | photo | §6 |
| N7 | `fig_deploy_loop.png` (+ `src/deploy_loop.dot`) | Closed-loop deploy block diagram: phone→TCP→PC (V-JEPA→AC→CEM)→ESP32. | new diagram | CPU | §13.1 |

### demo.json schema (for N3)
Top keys: `session, d(=4), stride(=2), dt, goal_lead_s(≈0.88), grid(15 steer pts), grid_thr(9 throttle pts), is_val, summary, frames`.
Per-frame keys: `k, cur_frame, goal_frame, human_steer, human_throttle, model_steer, model_throttle, contrast, contrast_thr, is_turn, sign_ok, E2(joint 15×9), E(steer 1-D), E_thr(throttle 1-D)`.
Good sessions: `session_20260608_173932` (672 frames), `session_20260607_162959`.

### Mermaid de-dup (4 figures render twice in the body)
Hình 1 `fig_data_pipeline.png` + mermaid; Hình 9 `fig_encoder_pipeline.png` + mermaid; Hình 10
`fig_arch_ours.png` + mermaid; Hình 12 `fig_arch_meta.png` + mermaid. → Keep the PNG in the body,
move the mermaid code blocks to Appendix “figure sources” (or delete, since `figures/src/*.mmd` holds them).

---

## COMMANDS TO REGENERATE FIGURES (run from repo root after `pip install -e .`)
```bash
# CPU (numbers hardcoded or read JSON / demo.json / logs):
PYTHONPATH=src python scripts/dataset_stats.py
PYTHONPATH=src python scripts/plot_dataset_overview.py
PYTHONPATH=src python scripts/plot_loss_curve.py
PYTHONPATH=src python scripts/plot_transfer.py
PYTHONPATH=src python scripts/plot_energy_landscape.py --demo data/demo/session_20260607_162959/demo.json   # reads demo.json → NO GPU
PYTHONPATH=src python scripts/plot_steer_tracking.py  --demo data/demo/session_20260607_162959/demo.json   # NO GPU
python scripts/plot_closed_loop.py logs/infer_20260613_171912.log --out docs/report/figures               # NO GPU (log parse)

# .dot → PNG. NOTE the filename remap: arch_*/encoder_pipeline/data_pipeline need a `fig_` prefix;
# the fig_*.dot already have it. e.g.:
dot -Tpng docs/report/figures/src/arch_ours.dot            -o docs/report/figures/fig_arch_ours.png
dot -Tpng docs/report/figures/src/arch_meta.dot            -o docs/report/figures/fig_arch_meta.png
dot -Tpng docs/report/figures/src/arch_predictor_detail.dot -o docs/report/figures/fig_arch_predictor_detail.png
dot -Tpng docs/report/figures/src/encoder_pipeline.dot     -o docs/report/figures/fig_encoder_pipeline.png
dot -Tpng docs/report/figures/src/data_pipeline.dot        -o docs/report/figures/fig_data_pipeline.png
dot -Tpng docs/report/figures/src/fig_cos_dropout_mechanism.dot -o docs/report/figures/fig_cos_dropout_mechanism.png

# GPU only for N4 (contrast vs horizon) — needs checkpoint + data/latents:
#   checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt , data/latents/* , data/demo/*
PYTHONPATH=src python scripts/probe_energy.py --turn-only -d 4 --n-windows 300 --with-throttle   # ref numbers
```

## KEY NUMBERS TO PRESERVE (must match Appendix §18.3 after translation; do not change, only language)
- Data: **209 sessions, 228,511 frames, 7.43 h** (KDS 28/53,076/1.73h; TowerPro 181/175,435/5.71h);
  throttle median 0.084; standstill 11.3%; 13,871 turning events; speed median 1.05 m/s; split 167/42.
- AC Predictor: **39,192,576 ≈ 39.2M** params; depth12 / pred_dim512 / 8 heads / 576 tokens; action 3-D; state 12-D.
- Deploy ckpt `cd4`: val L1 **0.5693**; rollout@1/2/3 = **0.744/0.703/0.697**.
- Transfer (TowerPro held-out): only-TowerPro **1.073** → pretrain-KDS+finetune **0.975** → mixed **0.65**.
- Tier-1 action-sens (300 turn windows): steer sign-turn **285/300=95%**, median |argminE−teacher| **0.146**,
  turn contrast steer **0.33**, throttle contrast **0.27**, throttle want-forward **83%** (median +0.11).
- Tier-2 (JOINT, 3 VAL ss, 893 turn frames): steer sign-turn **841/893=94.2%**, median |Δsteer| **0.118**;
  throttle want-forward **91.9%**, median +0.075 (human +0.090), median |Δthrottle| **0.033**; joint contrast **0.52**.
- §13.2 cross-lighting: same-session-near-time **66% ticks cos>0.3** vs different-lighting **0% ticks cos>0.3**.
- §13.3 standstill ablation (`probe_speed_confound.py`): contrast E(steer) **0.335 (moving) → 0.088 (standstill, ×3.8)**; fix = throttle floor TMIN=0.07.
- CEM: H=4; bicycle k_thr=1.588, k_drag=0.078, k_yaw=0.088; yaw_rate = k_yaw·steer·speed.

## References to add (verify from PDFs in `docs/` where present; don't invent details)
V-JEPA; V-JEPA 2; V-JEPA 2.1 (ViT-L distilled, 384, Dense Predictive Loss); V-JEPA 2-AC (Franka);
JEPA position paper (LeCun, `docs/10356_a_path_towards_autonomous_mach.pdf`); ViNG (image-goal nav);
Cross-Entropy Method (Rubinstein); AdamW; kinematic bicycle model; BNO055 (future work).

## Files
- Main report: `docs/report/2_REPORT_FULL.md`  ← rewrite here.
- Figures: `docs/report/figures/fig_*.png`; sources `docs/report/figures/src/*.{dot,mmd}`; stats `docs/report/figures/dataset_stats.json`.
- Reference numbers: report §18.3; `docs/HANDOFF.md` (live status).
- New figure scripts to create: `scripts/plot_results_summary.py` (N1), `scripts/plot_cross_lighting.py` (N2),
  `scripts/plot_energy_heatmap.py` (N3), `scripts/plot_contrast_vs_horizon.py` (N4), `scripts/plot_frame_montage.py` (N5),
  `docs/report/figures/src/deploy_loop.dot` (N7). Reuse loaders in `src/jepa_wm/` and sibling `plot_*`/`probe_*` scripts.

## VERIFY at the end
- Render `2_REPORT_FULL.md`: all image links resolve, every embedded+new figure shows, retained mermaid renders.
- `grep -nP "[\x{00C0}-\x{1EF9}]" docs/report/2_REPORT_FULL.md` returns nothing (no Vietnamese left); same for PNG text (visual).
- List of Figures/Tables numbers match captions; every `[n]` resolves to a References entry.
- All numbers still equal §18.3.
