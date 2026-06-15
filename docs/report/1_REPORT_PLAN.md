# BLUEPRINT BÁO CÁO CUỐI KỲ — môn Computer Vision

> File này = **kế hoạch viết** (section-by-section), không phải nội dung. Nội dung chi tiết ở
> `2_REPORT_FULL.md` (master) + `4_REPORT_PROSE_FULL.md` (prose). Slide ở `3_SLIDES.md`.
> **Mọi số trong bộ report đều tái lập được bằng script** (xem `2_REPORT_FULL.md` §18.1).
>
> **Cấu trúc (bản 2026-06-15, viết lại theo căn cứ):** mô tả **PHẦN CỨNG + DỮ LIỆU TRƯỚC** rồi tới
> kiến trúc; trọng tâm **TEACH & REPEAT**. Đã loại khỏi hệ chính: PiJEPA, SeqSLAM, SLAM, LeJEPA/LeWM,
> đồ-thị-ảnh (chỉ còn ở thử-nghiệm-phụ / tương lai). **Mọi số đếm/đo lại trực tiếp.**

---

## 0. Khung chốt (đọc trước khi viết)

- **Loại bài:** báo cáo môn CV kiểu paper. Kết quả âm (closed-loop) là điểm cộng (chiều sâu phân tích).
- **Câu chuyện 3 tầng:** *"Frozen V-JEPA 2.1 làm world model latent cho xe RC theo lối TEACH & REPEAT
  — (1) dynamics offline ĐỦ TỐT (thắng baseline đứng-yên, transfer chéo-servo, nhạy cả lái lẫn ga);
  (2) planner chọn JOINT lái+ga khớp người (~94% lái) open-loop; nhưng (3) closed-loop bung vì KHÂU
  ĐỊNH-VỊ (descriptor pooled-cosine nhạy sáng/heading) + CHẾ-ĐỘ-ĐIỀU-KHIỂN (vùng-chết đứng-yên, đã
  vá). Gap ở định-vị + điều khiển, KHÔNG ở representation."*
- **CẤM:** đừng claim "xe tự lái"; đừng claim open-loop 94% = tự lái; đừng đổ lỗi "V-JEPA nhiễu sáng"
  (phải nói rõ là **descriptor mean-pool+cosine ở khâu định-vị**, control patch-L1 vẫn bền); đừng dùng
  nhãn "OOD"; đừng nói "thiếu recovery trong data" (data CÓ — 13,871 sự kiện quẹo).
- **BẮT BUỘC:** đếm/đo **trực tiếp** mọi số bằng script; KHÔNG chép ghi chú cũ.

---

## 1. Cấu trúc section

| § | Section | Trọng tâm | Hình |
|---|---|---|---|
| — | Abstract | 3 tầng + 1 câu đóng góp (gloss thuật ngữ 1 dòng) | — |
| 1 | Giới thiệu & động lực | visual nav, world model, V-JEPA 2, novelty | — |
| 2 | **Khái niệm & thước đo** | identity, horizon, rollout@k, E, contrast, argmin, sign-turn, open/closed | — |
| 3 | Liên quan (gọn) | V-JEPA 2-AC = tham khảo; ViNG = goal-image | — |
| 4 | Phần cứng & thu data | xe+ESP32; pivot phone; **domain do servo KDS hỏng→TowerPro**; sync; δ_cam | fig_data_pipeline |
| 5 | Dữ liệu & thống kê | 209/228,511/7.43h; **data CÓ corrective driving**; split 167/42 | fig_data_* (8 hình) |
| 6 | Encoder + pre-encode | frozen 576 token; pipeline pre-encode (**BỎ phần R²(speed)**) | fig_encoder_pipeline |
| 7 | AC Predictor | interleave; block-causal; **chỉ ghi ≈39.2M (BỎ phép tính)**; giống/khác Meta; why-not-full-state | fig_arch_ours + fig_arch_meta |
| 8 | CEM + động học | bicycle-model; **yaw=k·steer·speed**; trễ tick | — |
| 9 | TẦNG 1 — Offline | rollout-vs-identity (tone down); transfer; action-sens RIÊNG (lái+ga) | fig_transfer + fig_energy_landscape |
| 10 | TẦNG 2 — Open-loop JOINT | thuật toán + pseudocode; d=4~0.9s; 94.2% / 91.9% | (demo) |
| 11 | TẦNG 3 — Closed-loop | **2 nguyên nhân**: A descriptor định-vị / B đứng-yên (đã vá) | bảng run |
| 12 | IMU + why-not-full-state | chất lượng kênh; → BNO055 | — |
| 13 | Hạn chế | 1 env, descriptor nhạy sáng, IMU nhiễu | — |
| 14 | Hướng phát triển | BNO055; learned descriptor; token-shift augment; 3DGS; RTK | — |
| 15 | Kết luận | 3 tầng; gap ở định-vị/control | — |
| — | Phụ lục | lệnh tái lập; config; bản đồ file | — |

---

## 2. Số liệu chốt (đã đếm/đo lại 2026-06-15)

- **Data:** 209 ss · 228,511 frame · 7.43h (KDS 28/1.73h · TowerPro 181/5.71h); throttle med 0.084;
  đứng-yên 11.3%; **13,871 sự kiện quẹo**; speed med 1.05 m/s; split 167/42.
- **Tham số:** AC predictor **39,192,576 ≈ 39.2M** (đếm checkpoint cd4).
- **Tầng 1:** cd4 ratio@1/2/3 = 0.744/0.703/0.697; transfer mixed→TowerPro **0.65** vs TowerPro-only
  **1.073**; action-sens (300 turn-window): lái **285/300=95%**, contrast turn **0.33** (all-frame ~0.41);
  ga contrast **0.27**, muốn-tiến **83%** (med +0.11).
- **Tầng 2 (JOINT, 3 ss VAL):** sign-turn lái **841/893 = 94.2%**; ga muốn-tiến **91.9%** (med +0.075);
  contrast joint med **0.52**.
- **Tầng 3.A:** lighting probe hạng-0/top1 79% (sáng-gần) vs hạng 41–62/top1 0–3% (sáng-xa).
- **Tầng 3.B:** ablation đứng-yên (`probe_speed_confound.py`) — contrast E(steer) tụt khi ép xe
  đứng-yên (cùng cảnh); fix = sàn ga TMIN=0.07.

---

## 3. Hình (`docs/report/figures/`) — đã sinh

| Hình | File | Nguồn |
|---|---|---|
| Pipeline data | `fig_data_pipeline.png` | mermaid `src/data_pipeline.mmd` (+ graphviz PNG) |
| Pipeline encoder | `fig_encoder_pipeline.png` | mermaid/graphviz |
| Kiến trúc của em | `fig_arch_ours.png` | mermaid/graphviz (so với Meta) |
| Kiến trúc Meta | `fig_arch_meta.png` | mermaid/graphviz |
| Thống kê data (8) | `fig_data_*.png` | `dataset_stats.py` |
| Transfer | `fig_transfer.png` | `plot_transfer.py` |
| Energy landscape | `fig_energy_landscape.png` | `plot_energy_landscape.py` (demo.json 162959) |

---

## 4. Checklist tự kiểm (chống bắt lỗi khi vấn đáp)

- [ ] Mọi số **đếm/đo lại bằng script**, không chép ghi chú cũ.
- [ ] Tham số ghi **39.2M** (BỎ "26M", BỎ phép tính dài).
- [ ] **BỎ phần encoder mã-hoá tốc-độ (R²)**, BỎ câu torch.hub, BỎ câu out-of-scope.
- [ ] Closed-loop A: nói rõ **descriptor mean-pool+cosine ở khâu định-vị**, KHÔNG "V-JEPA hỏng";
      control patch-L1 vẫn bền; confound heading.
- [ ] **BỎ nhãn OOD**; **BỎ "thiếu recovery"** (data có corrective driving).
- [ ] Closed-loop B: cơ chế yaw∝speed (trích code) + số ablation tái lập + đã vá (sàn ga).
- [ ] Thắng baseline = **điều kiện cần, chưa đủ** (không "mừng" quá).
- [ ] Open-loop 94% nói rõ **KHÔNG phải "xe tự lái"**; closed-loop **định tính**.
- [ ] Action-sensitivity: đo **riêng từng trục trước** (cô lập) → **joint sau** (Tầng 2).
