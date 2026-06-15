# BLUEPRINT BÁO CÁO CUỐI KỲ — môn Computer Vision

> File này = **kế hoạch viết** (section-by-section), không phải nội dung. Nội dung chi tiết ở
> `2_REPORT_FULL.md` (master) + `4_REPORT_PROSE_FULL.md` (prose). Slide ở `3_SLIDES.md`.
> **Mọi số trong bộ report đều tái lập được bằng script** (xem `2_REPORT_FULL.md` §18.1).
> Convert: `pandoc 2_REPORT_FULL.md -o report.tex`.
>
> **Cấu trúc mới (2026-06-15):** mô tả **PHẦN CỨNG + DỮ LIỆU TRƯỚC**, rồi mới tới kiến trúc; trọng tâm là
> **TEACH & REPEAT** (đồ-thị-ảnh chỉ là thử nghiệm phụ). Đã loại bỏ khỏi hệ chính: PiJEPA, SeqSLAM, SLAM,
> LeJEPA/LeWorldModel (chỉ còn ở "hướng tương lai/thử nghiệm"). Số đã đếm/đo lại: **tham số 39.2M** (không
> phải 26M), **R²(speed)=+0.30** (không phải −1.1), data **209 ss / 228,511 frame / 7.43 h**.

---

## 0. Khung chốt (đọc trước khi viết 1 dòng)

- **Loại bài:** báo cáo môn CV, kiểu paper có cấu trúc. Negative finding là ĐIỂM CỘNG (chiều sâu phân tích).
- **Câu chuyện 1 dòng (3 tầng):** *"Frozen V-JEPA 2.1 làm world model latent cho xe RC theo lối TEACH &
  REPEAT — (1) dynamics offline ĐỦ TỐT (thắng baseline, transfer chéo-servo, nhạy cả lái lẫn ga); (2)
  planner chọn JOINT lái+ga khớp người lái (~94% lái, ga tự chọn) open-loop; nhưng (3) closed-loop bung vì 3 nguyên nhân (descriptor không
  bất-biến-sáng / đứng-yên / no-recovery). Gap ở định-vị + điều khiển, KHÔNG ở representation."*
- **4 thông điệp phải đọng lại:**
  1. **Novelty:** đánh giá ĐẦU TIÊN họ V-JEPA 2 trên robot DI ĐỘNG (Meta chỉ làm robot-arm).
  2. **Tầng 1 — Offline rigorous:** thắng identity (cd4 0.744), **cross-domain transfer (0.65 vs 1.073)**,
     action-sensitivity đo được **cả lái (96%, contrast 0.413) lẫn ga (0.298, 81% muốn tiến)**.
  3. **Tầng 2 — Planner open-loop JOINT (lái×ga):** lái khớp **~94% sign-turn** (841/893) + ga tự chọn muốn-tiến 92% → "lập kế hoạch" LÀNH.
  4. **Tầng 3 — Negative finding có cơ chế, phân rã 3 nguyên nhân + đính chính** kết luận sai.
- **4 điều CẤM:** (a) đừng headline `0.958` (hơn identity 4% — mỏng); (b) đừng claim "xe tự lái được"; (c)
  **đừng claim open-loop 94% = tự lái** (nó là probe trực quan, KHÔNG đóng vòng); (d) đừng giấu confound
  ánh sáng — nêu thẳng, nó CỦNG CỐ luận điểm "gap ở descriptor/control, không ở dynamics".
- **Điều BẮT BUỘC (yêu cầu mới):** đếm/đo **trực tiếp** mọi con số (tham số, R², thống kê data); KHÔNG chép
  số từ ghi chú cũ.

---

## 1. Cấu trúc section (mô tả phần cứng/data TRƯỚC kiến trúc)

| § | Tên section | Phải có gì | Số/Hình chủ lực | Nguồn (FULL) |
|---|---|---|---|---|
| — | **Abstract** | 3 tầng + 1 câu đóng góp | cd4 0.744; cross-domain 0.65/1.073; open-loop 94%; closed-loop 0/~10 | §1 |
| 1 | **Giới thiệu** | Visual nav; world model; V-JEPA 2; novelty; teach&repeat (KHÔNG bản đồ hình học) | — | §2 |
| 2 | **Related work** (gọn) | V-JEPA 2(-AC) = kiến trúc tham khảo; ViNG = ý tưởng goal-image | — | §4 |
| 3 | **Phần cứng & thu data** | Xe+ESP32+servo/ESC; 2 domain servo; pivot phone onboard; sync; δ_cam; GPS | — | §5 |
| 4 | **Dữ liệu & thống kê** | 209 ss / 228,511 frame / 7.43h; phân bố steer/throttle/speed; split 167/42 | bảng + 5 biểu đồ | §6 |
| 5 | **Encoder + đo tốc độ** | frozen 576 token; pre-encode; **R²(speed)=+0.30 (đo lại, yếu)** | bảng ridge | §7 |
| 6 | **AC Predictor** | interleave; block-causal; **phép tính tham số 39.2M**; giống/khác Meta + vì sao; vì sao không đoán full state | Hình 1 + bảng tham số | §8 |
| 7 | **TẦNG 1 — Offline** ✅ | rollout-vs-identity; cross-domain; action-sens lái + GA; cd4_as3 âm | Bảng A,C + Hình 2 | §9 |
| 8 | **TẦNG 2 — Open-loop JOINT** ✅ | demo lưới 2-D lái×ga; lái 93% + ga tự chọn; trung thực OPEN-LOOP | bảng + demo 2-D | §10 |
| 9 | **TẦNG 3 — Closed-loop** ❌ | bảng run; **3 nguyên nhân** (A descriptor / B đứng-yên / C no-recovery) | Bảng D | §12 |
| 10 | **Đánh giá IMU + vì sao không đoán full state** | chất lượng kênh IMU; 4 lý do; → BNO055 | — | §13 |
| 11 | **Đính chính & bài học** | 26M→39.2M; OOD bị bác; R²=−1.1 sai; geosteer | bảng đính chính | §14 |
| 12 | **Hạn chế** | 1 env, no-recovery, confound sáng, IMU nhiễu | — | §15 |
| 13 | **Hướng phát triển** | **BNO055**; recovery-data; learned descriptor; 3DGS; RTK | — | §16 |
| 14 | **Kết luận** | 3 tầng; gap ở định-vị/control; negative finding trung thực | — | §17 |
| — | **Phụ lục** | Lệnh tái lập; config cd4; bản đồ file | — | §18 |

**Tổng ước lượng:** 11–13 trang (2 cột) hoặc 15–19 trang (1 cột).

---

## 2. Bảng số liệu (copy thẳng — ĐÃ đếm/đo lại trực tiếp)

**Dữ liệu (`scripts/dataset_stats.py`):**
- 209 session · **228,511 frame** · **7.43 giờ** (KDS 28/1.73h · TowerPro 181/5.71h) · ~8.5 fps.
- throttle median 0.084 · đứng-yên 11.3% · 13,871 sự kiện quẹo · speed median 1.05 m/s · split 167/42.

**Tham số (đếm từ checkpoint cd4):** AC predictor **39,192,576 ≈ 39.2M** (12 lớp ×3.15M = 37.8M = 96.5%).

**Encoder (`scripts/measure_speed_r2.py`):** R²(speed) held-out **+0.30** (λ=1000; train 0.72) → tín hiệu
tốc độ trong latent YẾU, không phải "mù hoàn toàn / −1.1".

**Tầng 1:** cd4 ratio@1/2/3 = 0.744/0.703/0.697 · cross-domain mixed→TowerPro 0.65 vs TowerPro-only 1.073 ·
action-sens lái 96% / contrast 0.413 · ga contrast 0.298 (81% muốn tiến, med +0.094) · cd4_as3 contrast 0.274 (âm).

**Tầng 2 (JOINT lái×ga, 3 ss VAL best):** sign-turn lái 841/893 = **94.2%** · |Δsteer| med ~0.07 · ga muốn-tiến **91.9%**, ga med **+0.075** (người +0.090) · contrast joint 0.524.

**Tầng 3:** 0/~10 run về đích · lighting probe: hạng-0 top1 79% (sáng-gần) vs hạng-41 top1 0–3% (sáng-xa) ·
speed=0 ablation contrast 0.41→0.11 · CEM tick 32/1 0.50s … 256/2 5.51s · dynamics k_thr 1.588 / k_yaw 0.088.

---

## 3. Hình cần có (`docs/report/figures/`)

| Hình | Mô tả | Trạng thái |
|---|---|---|
| 1 | Kiến trúc hệ thống | `fig_architecture.png` (graphviz) |
| 2 | Energy landscape lái | `fig_energy_landscape.png` |
| D1–D5 | Phân bố steer/throttle/speed + độ-dài-session + giờ | ✅ `fig_data_*.png` (sinh bởi `dataset_stats.py`) |
| 7 | Ảnh chụp/heatmap demo open-loop | từ `demo_web.py` (export) |

---

## 4. Thứ tự viết (ưu tiên ROI)

1. §6 AC Predictor (phép tính tham số) + §7 Tầng 1 (số mạnh nhất) → viết trước.
2. §3–4 phần cứng + dữ liệu (mô tả nền) + §8 Tầng 2.
3. §9 Tầng 3 (3 nguyên nhân) + §10 IMU + §11 đính chính.
4. Abstract + Kết luận viết SAU CÙNG.

---

## 5. Checklist trung thực (để không bị bắt lỗi khi vấn đáp)

- [ ] Mọi số đã **đếm/đo lại bằng script**, không chép ghi chú cũ.
- [ ] Tham số ghi **39.2M** (kèm phép tính), KHÔNG ghi 26M.
- [ ] R²(speed) ghi **+0.30 (yếu)**, KHÔNG ghi −1.1.
- [ ] Gọi V-JEPA 2-AC là **kiến trúc tham khảo** (giống/khác/vì-sao), KHÔNG gọi "port trung thực".
- [ ] Teach & repeat là **hệ chính**; đồ-thị-ảnh + các nhánh khác là **thử nghiệm phụ / tương lai**.
- [ ] Open-loop 94% nói rõ **KHÔNG phải "xe tự lái"**.
- [ ] Closed-loop nói rõ **định tính** (1 env, 0 về đích).
- [ ] Không nhắc SLAM / PiJEPA / SeqSLAM như thành phần của hệ.
