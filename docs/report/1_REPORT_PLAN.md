# BLUEPRINT BÁO CÁO CUỐI KỲ — môn Computer Vision

> File này = **kế hoạch viết** (section-by-section), không phải nội dung. Nội dung chi tiết nằm ở
> `2_REPORT_FULL.md`. Slide ở `3_SLIDES.md`. Mọi số trong đây đã verify từ repo (HANDOFF.md /
> CLOSED_LOOP_FAILURE.md / VJEPA2_AC_CAR.md). Convert sang LaTeX: `pandoc 2_REPORT_FULL.md -o report.tex`.

---

## 0. Khung chốt (đọc trước khi viết 1 dòng)

- **Loại bài:** báo cáo môn CV, kiểu paper có cấu trúc. Negative finding là ĐIỂM CỘNG (chiều sâu phân tích).
- **Câu chuyện 1 dòng:** *"Frozen V-JEPA 2.1 làm world model latent cho xe RC — biểu diễn ĐỦ TỐT offline
  (thắng baseline, transfer chéo-servo), nhưng triển khai closed-loop bung ở điểm visual-mismatch vì
  thiếu lateral-recovery. Gap ở tầng nav-robustness+control, KHÔNG ở representation."*
- **3 thông điệp phải đọng lại ở người chấm:**
  1. **Novelty:** đánh giá ĐẦU TIÊN họ V-JEPA 2 trên robot DI ĐỘNG (Meta chỉ làm robot-arm).
  2. **Offline rigorous:** thắng identity baseline (cd4 ratio 0.744), **cross-domain servo transfer có lợi
     (0.65 vs 1.073)**, action-sensitivity đo được (58/60, contrast 0.37).
  3. **Negative finding có cơ chế:** cos-dropout → mất gradient → no-recovery → bung. Đo trên ~10 run.
- **3 điều CẤM:** (a) đừng headline `0.958` (hơn identity 4% — mỏng); (b) đừng claim "xe tự lái được";
  (c) đừng giấu confound ánh sáng — nêu thẳng, nó CỦNG CỐ luận điểm "gap ở control, không ở representation".

---

## 1. Cấu trúc section + nội dung + số liệu + nguồn

| § | Tên section | Phải có gì | Số/Hình chủ lực | Nguồn trong repo | Độ dài |
|---|---|---|---|---|---|
| — | **Abstract** | Vấn đề + cách làm + offline win + negative deploy + 1 câu đóng góp | cd4 0.744; cross-domain 0.65/1.073; closed-loop 0/~10 | FULL §1, §7, §11 | ~200 từ |
| 1 | **Giới thiệu** | Visual navigation; world model; V-JEPA 2; **novelty**; phạm vi bài (goal-reaching, KHÔNG SLAM) | — | FULL §1–2 | 1 trang |
| 2 | **Related work** | V-JEPA 2(-AC), JEPA; ViNG/ViKiNG (teach&repeat/topo-nav); CEM/MPC latent; PiJEPA | — | docs PDF; FULL §3 | 0.75 trang |
| 3 | **Phương pháp** | Frozen encoder→patch token; AC predictor block-causal; CEM+CarDynamics; TopoGraph; teach&repeat | sơ đồ kiến trúc (Hình 1) | FULL §5–9 | 2–3 trang |
| 4 | **Thiết lập thực nghiệm** | Rig (phone onboard), data (209 ss/228k frame, 2 servo domain), δ_cam, GPS, split frozen | bảng data; δ_cam 100ms; GPS 0.44m | FULL §4 | 1 trang |
| 5 | **Kết quả OFFLINE** (lõi mạnh) | rollout-vs-identity; baseline; **cross-domain transfer**; action-sensitivity; cd4_as3 ablation negative; localize | Bảng A, B, C + Hình 2 (energy) | FULL §7–8 | 2 trang |
| 6 | **Triển khai closed-loop** | Inference loop; teach&repeat; bảng 6 run; định lượng "bám nửa đầu rồi bung" | Bảng D (6 run) | FULL §10 | 1 trang |
| 7 | **Phân tích thất bại** (lõi CV) | Cơ chế cos-dropout (Hình 3 vòng xoáy); bằng chứng KHÔNG-phải-teach-xấu; so Meta/ViNG | self-gap 0.070/0.094; 66% vs 0% >0.3 | FULL §11 | 1.5 trang |
| 8 | **Thảo luận & Hạn chế** | 1 env, no-recovery-data, GPS 1Hz, confound sáng; ý nghĩa cho deploy world-model | — | FULL §13 | 0.75 trang |
| 9 | **Hướng phát triển** | Recovery-data retrain; 3DGS sim; seq-matching/reachability head; RTK | — | FULL §14 | 0.5 trang |
| 10 | **Kết luận** | Representation đủ tốt; gap ở nav-robustness; negative finding trung thực | — | FULL §15 | 0.25 trang |
| — | **Phụ lục** | Lệnh tái lập; config cd4; bản đồ file; bảng bug | — | FULL §12, §16 | tuỳ |

**Tổng ước lượng:** 10–12 trang (2 cột) hoặc 14–18 trang (1 cột). Quá đủ cho báo cáo môn.

---

## 2. Bảng số liệu (copy thẳng vào báo cáo — đã verify)

**Bảng A — World model offline (rollout@k / identity; <1 = thắng baseline "đứng yên", thấp hơn = tốt hơn)**

| Model | @1 | @2 | @3 | Ghi chú |
|---|---|---|---|---|
| **cd4 (deploy)** — V-JEPA 2.1 ViT-L 384, patch+state, depth12, ~26M | **0.744** | **0.703** | **0.697** | frozen split, 2000 window |
| vjepa_ac (pooled, 7.4M), 5-seed CV | 0.958 ± 0.024 | — | — | 4/5 seed <1, var thấp (bằng chứng ỔN ĐỊNH) |
| vjepa_ac_pool (baseline pooled) | 0.867 | — | — | ablation: patch+state có đáng? |
| **LeWM** (pixel JEPA e2e, ~22M) — baseline | 0.97 ± 0.15 | — | ≥1 (horizon dài) | 2/5 fold FAIL → KHÔNG ổn |
| cd4_as3 (auto_steps 3) — ablation | 0.745 | 0.699 | 0.686 | pred tốt hơn NHƯNG action-sens kém → bỏ |

**Bảng B — Cross-domain servo transfer (đóng góp nổi bật)**

| Train | Eval trên TowerPro held-out (@1) | Diễn giải |
|---|---|---|
| **Mixed (KDS+TowerPro)** | **0.65** | thắng identity rõ |
| TowerPro-only | 1.073 | TỆ HƠN đứng yên |
→ KDS (giàu steering, servo khác) **transfer sang** TowerPro → train chéo-domain-servo GIÚP ÍCH.

**Bảng C — Action-sensitivity (CEM thực sự "đọc" được hành động?)**

| Đo | cd4 | cd4_as3 |
|---|---|---|
| argmin-E đúng hướng cua (probe_energy --turn-only, d4) | **58/60** | 54/60 |
| contrast (Emax−Emin)/Emin | **0.37** | 0.274 |
| Δsteer recovery / Δthrot | 0.16 / 0.04 | — |
| contrast theo khoảng cách target | d2 0.443 / d4 0.355 / d8 0.270 | — |

**Bảng D — Closed-loop teach&repeat (route ~15m; KHÔNG run nào về đích)**

| Run | tick | config | bám tốt tới | bung tại (cos) | kết cục |
|---|---|---|---|---|---|
| 163607 | 1.13s | 59sg, fast | **sg18 (xt<0.5m)** | sg21 (cos 0.07) | bung trái +3.2m |
| 163831 | 2.82s | 59sg, slow | sg8 | sg10 (cos 0.27) | trôi −2.4m |
| 164827 | 2.90s | 59sg, slow | sg12 | sg27 | trôi trái +2.8m |
| 171022 | 2.82s | geosteer ON | sg20 | sg23 | DIVERGE (rotvec hỏng) |
| **171912** | 1.78s | **pure-visual sạch** | sg6 | **sg7 (cos 0.02)** | veer trái → bụi cỏ |

**Bảng E — Nav (TopoGraph)**

| Đo | Giá trị |
|---|---|
| Graph 92-session (28 KDS + 64 TowerPro) | 29,699 node, 1 component 100% |
| Localize LOSO | median **2.1m** (<8m: 88%) |
| Routing thành công | 100% |
| Route bám tuyến người | median 2.3m |
| centered-cos phân biệt vị trí | tại-chỗ ~1.0 / kế ~0.58 / cách-2 ~0.37 (raw-cos vô dụng 0.95–0.99) |

---

## 3. Hình cần có — TRẠNG THÁI (đã generate phần lớn → `docs/report/figures/`)

| # | Hình | Trạng thái | File / nguồn |
|---|---|---|---|
| 1 | **Kiến trúc hệ thống** (frame→V-JEPA frozen→patch→AC predictor→CEM) | ✅ **CÓ (PNG)** + mermaid | `figures/fig_architecture.png` |
| 3 | **Vòng xoáy cos-dropout** (sơ đồ nhân-quả) | ✅ **CÓ (PNG)** + mermaid | `figures/fig_cos_dropout_mechanism.png` |
| 4 | **Route map đồ thị topo + route + ảnh subgoal** | ✅ **CÓ (ảnh thật)** | `figures/fig_route_graph.png` |
| 5a | **cos-dropout (run thật)**: cos rơi <0.1 + raw-steer bão hòa 1.0 | ✅ **CÓ (ảnh thật)** | `figures/fig_cos_dropout_20260613_171912.png` |
| 5b | **Quỹ đạo bám-rồi-bung** (xy tô màu theo cos) | ✅ **CÓ (ảnh thật)** | `figures/fig_trajectory_20260613_171912.png` |
| 2 | **Energy landscape theo steering** (E(steer) basins + argmin-vs-teacher 58/60) | ✅ **CÓ (ảnh thật)** | `figures/fig_energy_landscape.png` |
| 6 | **Ảnh rig phần cứng** (phone trên xe + ESP32) | ⏳ user tự chụp | — |

**Tự sinh lại / sinh cho run/checkpoint khác:**
- Closed-loop (cos-dropout + quỹ đạo, KHÔNG cần GPU): `python scripts/plot_closed_loop.py logs/infer_<...>.log --out docs/report/figures`
- Route map: `PYTHONPATH=src python scripts/viz_route.py --graph data/graph/topograph.pt --out docs/report/figures/fig_route_graph.png`
- Energy landscape (cần GPU + `data/latents_*_patch_384`): `PYTHONPATH=src python scripts/probe_energy.py --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt --turn-only -d 4 --n-windows 60 --plot docs/report/figures/fig_energy_landscape.png`

> **Bộ hình giờ ĐỦ — 6 file PNG dùng ngay** trong `figures/`: 2 sơ đồ (kiến trúc + cơ chế lỗi, render
> graphviz) + 4 biểu đồ/map thật (route map, energy landscape, cos-dropout, quỹ đạo). Chỉ còn **ảnh rig
> phần cứng** là tuỳ bạn chụp (chèn vào §4 — `4_REPORT_PROSE_FULL.md` đã chừa chỗ "*Vị trí chèn ảnh rig*").

---

## 4. Thứ tự viết trong 1 ngày (ưu tiên ROI)

1. **Dán Bảng A–E + Hình 3, 4 trước** (đã có sẵn — 30').
2. **Viết §5 (offline) + §7 (failure)** — 2 section lõi, số đã xong → viết nhanh, điểm cao nhất.
3. **§3 phương pháp + §6 closed-loop** — mô tả hệ thống.
4. **§1 intro + §2 related** — đóng khung novelty.
5. **§8–10 + abstract** — viết cuối khi đã thấy toàn cảnh.
6. Phụ lục = copy từ FULL §12/§16.
> Nếu cạn giờ: §5 + §7 + §6 + abstract là bộ KHUNG TỐI THIỂU vẫn ra một báo cáo mạnh.

## 5. Checklist trung thực (để không bị bắt lỗi khi vấn đáp)
- [ ] Mọi số có nguồn (split frozen, n window). Closed-loop ghi rõ **n≈10 run, 1 env, 0 về đích**.
- [ ] Phân biệt rõ **representation (tốt)** vs **control/nav-robustness (gap)** — đây là luận điểm trung tâm.
- [ ] Nêu confound ánh sáng ở Limitations, đừng giấu.
- [ ] cd4_as3 trình bày như **ablation âm** (deeper rollout → energy phẳng) — thể hiện rigor.
- [ ] Không gọi 256px là "faithful" (đó là lựa chọn compute của Meta) — xem FULL §5.
