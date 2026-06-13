---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Action-Conditioned World Model (V-JEPA 2.1) cho Xe RC'
footer: '[Họ tên] · [Lớp/Môn CV] · 2026-06'
---

<!--
HƯỚNG DẪN RENDER:
- VS Code: cài extension "Marp for VS Code" → mở file → Export PDF/PPTX.
- CLI: `npx @marp-team/marp-cli 3_SLIDES.md -o slides.pdf` (hoặc --pptx).
- Mỗi `---` = 1 slide. Khối <!-- --> dưới mỗi slide = speaker notes (Marp đưa vào ghi chú PPTX).
- Thời lượng gợi ý: ~12–15 phút + Q&A. Dồn thời gian cho slide 11–14 (kết quả + phân tích lỗi).
-->

# World Model Hành-động-điều-kiện dựa trên **V-JEPA 2.1** cho Điều hướng Xe RC

### Đánh giá Offline & Phân tích Triển khai Closed-loop

**[Họ tên] — [MSSV]**
Báo cáo cuối kỳ — [Môn Computer Vision] — [GVHD]
2026-06

<!--
Mở bài 1 câu: "Em dùng một foundation video encoder đóng băng làm world model để xe RC tự điều hướng
bằng ảnh-mục-tiêu. Offline rất hứa hẹn; closed-loop bộc lộ một giới hạn thú vị mà em phân tích kỹ."
-->

---

## Bài toán & Động lực

- **Điều hướng bằng thị giác** không cần SLAM/bản đồ hình học.
- Ý tưởng: học một **world model** "hành động nào → đổi hình ảnh nào" trong **không gian latent**, rồi
  **lập kế hoạch** đưa ảnh hiện tại về **ảnh-mục-tiêu**.
- **V-JEPA 2.1** (ViT-L, đóng băng): foundation video encoder, dự đoán trong không gian *feature* (không
  pixel) → đặc trưng patch chất lượng cao.
- Meta đã chứng minh **V-JEPA 2-AC** trên **cánh tay robot**. Câu hỏi của bài:

> **Biểu diễn này có dùng được cho một robot DI ĐỘNG, ngoài trời, động lực học + domain-shift thật?**

<!-- Nhấn: đây là câu hỏi NCKH trung tâm, và là góc Computer Vision (biểu diễn + place recognition + robustness). -->

---

## Đóng góp

1. **Đánh giá ĐẦU TIÊN họ V-JEPA 2 trên robot di động (xe RC).** *(Meta chỉ làm robot-arm.)*
2. **Pipeline offline rigorous:** thắng baseline identity; **transfer chéo-domain-servo có lợi**; độ nhạy
   hành động đo được.
3. **Negative finding có cơ chế:** closed-loop bám nửa đầu route rồi **bung ở điểm "cos-dropout"** vì
   thiếu lateral-recovery — *giới hạn ở control/nav-robustness, KHÔNG ở representation.*

<!-- Câu chốt: "3 đóng góp — 1 novelty, 1 kết quả offline vững, 1 phân tích thất bại trung thực." -->

---

## Phạm vi bài toán (chốt rõ)

**Teach & Repeat kiểu ViNG/ViKiNG:** lái 1 vòng "dạy" chuỗi **subgoal ảnh** → xe "lặp lại", mỗi subgoal
CEM lái tới.

| ✅ Trong phạm vi | ❌ Ngoài phạm vi (cố ý) |
|---|---|
| Bám tuyến đã dạy | Né vật cản |
| Pop subgoal (GPS + ảnh) | SLAM / bản đồ 3D toàn cục |
| Điều khiển servo bằng CEM | Đường chưa từng đi |

**Kiến trúc 2 tầng** (giúp quy trách nhiệm khi phân tích lỗi):
- **Navigation** = thị giác + GPS (action-agnostic) — "đang ở đâu, đi qua subgoal nào".
- **Control** = V-JEPA + AC predictor + CEM (servo-specific) — "đạp/đánh lái bao nhiêu".

---

## Tổng quan hệ thống

![h:250](figures/fig_architecture.png)

- **Encode offline 1 lần** → train đọc latent trực tiếp (**~50–100× nhanh**, không forward V-JEPA khi train).
- **KHÔNG bao giờ backprop qua encoder.**

<!-- Đây là slide "method ở mức cao". Chi tiết kiến trúc ở slide kế. -->

---

## Phần cứng & Dữ liệu

- **Bước ngoặt:** link video WFB 5.8GHz **vỡ ở 50m** (trễ 92→310ms) → **đặt điện thoại Android lên xe**
  (camera + ghi + relay). Frame & telemetry **chung 1 đồng hồ** → hết lệch clock. *(δ_cam ≈ 100ms, đã hiệu chỉnh.)*
- **Lái tay** FlySky i-BUS; **ESP32-S3** điều khiển servo + ESC.
- **209 session ≈ 228k frame**, **2 domain servo:**

| Tập | #ss | Đặc điểm |
|---|---|---|
| KDS (cũ) | ~28 | steering đủ dải, **ga ~hằng** (≈ steering-only) |
| TowerPro (mới) | 181 | **ga biến thiên** (reverse 9–14%) |

- GPS ~**1Hz**, nhiễu **0.44m** → chỉ làm cổng pop, **lái 100% bằng vision**.

---

## Encoder V-JEPA 2.1 — một phát hiện CV

- ViT-L 384 đóng băng, **encode TỪNG frame** → patch tokens (576 × 1024-D).
- **Phát hiện đo được:** latent **mù vận tốc** — R²(speed) = **−1.1** (single-frame), nhồi clip cũng ≈ 0.
  → vì model chạy **image-path (tubelet=1)** = không tích chập thời gian.

> **Hệ quả thiết kế:** tốc độ phải vào qua **STATE token** (GPS speed), KHÔNG qua multi-frame.
> Góc lái thì **đã nằm trong ảnh** (camera thấy bánh trước).

<!-- Đây là một điểm "hiểu sâu về model" — người chấm CV thích. Nhấn: video encoder vẫn có thể mù vận tốc nếu chạy image-path. -->

---

## AC Predictor (đóng góp chính)

Port **trung thực** V-JEPA 2-AC của Meta sang xe di động:
- Interleave `[action, state, patch]` mỗi frame → **predictor block-causal** → ẑ tuyệt đối.
- **per-token LayerNorm**, **L1 teacher-forcing + rollout 2-step**, CEM energy `‖P − z_goal‖₁`.
- ~**26M** tham số (encoder đóng băng).

**Lệch có chủ ý (ghi minh bạch):** state IMU 10-D (thay pose cánh tay) · pos-emb học được (thay 3D-RoPE) ·
depth 12 (thay 24, tránh overfit) · **bicycle-model dynamics** (thay `compute_new_pose`).

---

## Cách ĐO (vì sao không tin val loss)

- **rollout@k / identity** = MSE(model) / MSE("đứng yên"). **< 1 = thắng baseline; thấp hơn = tốt hơn.**
- **Action-sensitivity (energy-probe):** quét E(steer), xem **argmin có đúng hướng cua** + **contrast** sâu cỡ nào.

> `val_pred` đơn lẻ **lừa người**: latent collapse + bỏ qua action vẫn cho val thấp.
> Luôn xem **rollout-vs-identity + action-sensitivity.**

<!-- Slide phương pháp luận — thể hiện sự cẩn thận. -->

---

## Kết quả Offline (1): thắng baseline ổn định

| Model | @1 | @2 | @3 |
|---|---|---|---|
| **cd4 (deploy)** — V-JEPA 2.1 + patch+state | **0.744** | **0.703** | **0.697** |
| vjepa_ac pooled (5-seed CV) | 0.958 ± 0.024 | — | — |
| **LeWM** (pixel-JEPA, baseline) | 0.97 ± 0.15 | — | ≥1 |

- Model chính **<1 ở mọi horizon**, ổn định (var thấp).
- Baseline LeWM **không ổn định** (2/5 fold fail, ≥1 ở horizon dài).

<!-- Headline số: 0.744. Đừng dừng ở 0.958 (hơn identity chỉ 4%). -->

---

## Kết quả Offline (2): **Cross-domain transfer** ⭐

| Train | Eval trên **TowerPro** held-out (@1) |
|---|---|
| TowerPro-only | **1.073** ← *tệ hơn đứng yên!* |
| **Mixed (KDS + TowerPro)** | **0.65** ← *thắng rõ* |

> Train **trộn** với KDS (servo KHÁC, giàu steering) **giúp ích** cho TowerPro.
> **Đa dạng hành động/domain > so-khớp-domain.**

<!-- Đây là số "đắt" và mới nhất của bài. Dành thời gian giải thích. -->

---

## Kết quả Offline (3): độ nhạy hành động — energy landscape

![h:325](figures/fig_energy_landscape.png)

- **argmin-E đúng hướng cua 58/60**, contrast 0.355 → **model KHÔNG dốt cua offline** (đáy energy rõ, đúng phía).
- Ablation âm **cd4_as3** (auto_steps 3): pred tốt hơn nhưng energy cua **phẳng đi** (54/60) → **giữ cd4**.

> cos-dropout closed-loop **làm phẳng chính landscape này** — thất bại ≠ năng lực model.

---

## Navigation: Topological Graph

- Node = frame (latent V-JEPA + GPS + heading); cạnh temporal + loop-closure (GPS-gate <8m).
- **Graph 92-session = 29,699 node, 1 component 100%.**
- **Localize LOSO: trung vị 2.1m** (<8m: 88%); **routing 100%**.
- **Place recognition** (centered-cos): tại-chỗ ~1.0 / kế ~0.58 / cách-2 ~0.37 *(raw-cos vô dụng 0.95–0.99)*.

![h:330](figures/fig_route_graph.png)

<!-- Hình: đồ thị topo 209-session (~33.6k node, xám) + 1 route Dijkstra (xanh) + chuỗi ảnh subgoal CEM lái tới. Generate: python scripts/plot_closed_loop.py ... / scripts/viz_route.py. -->

→ Place recognition + chuỗi ảnh subgoal: phần thị giác **hoạt động tốt** offline.

---

## Closed-loop: Teach & Repeat ngoài thực địa

- **Teach:** lái tay, chụp subgoal ảnh+GPS dọc tuyến (~15m).
- **Repeat:** phone stream → **PC: V-JEPA → AC predictor → CEM** → 2-byte action → ESP32.
- **Trễ CEM:** 32/1 ≈ 0.5s … 256/2 ≈ 5.5s/quyết định (encoder cần GPU, không chạy trên phone).

| Run | bám tốt tới | bung tại (cos) | kết cục |
|---|---|---|---|
| 163607 | **sg18 (xt<0.5m)** | sg21 (0.07) | bung +3.2m |
| 171912 (sạch) | sg6 | **sg7 (0.02)** | veer → bụi cỏ |

> **0/~10 run về đích.** Bám nửa đầu tốt → **bung ở cos-dropout**. Knob chỉ **dời** điểm bung.

---

## Phân tích thất bại: vòng xoáy **cos-dropout**

![h:300](figures/fig_cos_dropout_mechanism.png)

- **cos<0.1** → goal không phân-biệt-được trong latent → **energy phẳng theo steering** → CEM lái ~random.
- **No-recovery:** teach chụp toàn bộ **khi xe ở GIỮA tuyến** → **không ảnh nào dạy "lệch 2m bẻ về đâu"**.

<!-- Đây là slide "đắt" nhất — đi chậm. Có thể render bản mermaid trong report. -->

---

## Bằng chứng đo được (run thật 171912)

![h:400](figures/fig_cos_dropout_20260613_171912.png)

cos giữ ~0.25 (sg4–7) → **rơi <0.1 ở sg8 → âm ở sg9** (vùng đỏ); đồng thời **|raw steer| bão hòa 1.0**
= CEM mất gradient, lái full-lock. *(Dữ liệu parse trực tiếp từ log inference.)*

---

## Bằng chứng: **KHÔNG** phải teach xấu / cảnh tự-giống

- **Embedding teach tốt đều:** self-gap parkfix3 **0.070** / parkfix_5 **0.094** (phân biệt được như nhau).
- **Cos-quality khi chạy phụ thuộc ánh sáng teach-vs-repeat:**
  - parkfix3 (teach sáng, chạy ngay) → **66% tick cos>0.3** → bám tới sg18–57.
  - parkfix_5 (teach 14:11, chạy 14:50 nắng gắt) → **0% cos>0.3**.

> Thủ phạm = **domain-shift ánh sáng/góc nhìn giữa teach và repeat**, **KHÔNG** phải encoder/biểu diễn.

<!-- Kết luận CV cốt lõi: representation tốt; gap ở robustness của khớp-live + thiếu recovery. -->

---

## So với Meta & ViNG

- **Meta (robot-arm):** cảnh bàn cố định, action đổi-cảnh **lớn+tức thì**, **không** heading/sáng/lệch.
  "Chính xác cm" = khớp proprioception tay máy — **khác hệ đo**.
- **Xe ngoài trời:** đổi-cảnh **nhỏ** + cos-dropout + no-recovery → **khó hơn về robustness**.
- **ViNG/ViKiNG chạy được** vì policy **train trên data có recovery** (lệch→về) — data của ta **thiếu**.

> Khoảng cách "latent tốt offline" → "lái được ngoài trời" nằm ở **dữ liệu recovery + control**.

---

## Hạn chế

- Closed-loop: **1 môi trường, ~10 run, 0 về đích, chưa có success-rate metric** → định tính + cơ chế.
- **Thiếu recovery data** (teach 1-lượt-giữa-line).
- **Confound ánh sáng** (teach vs repeat khác giờ).
- GPS 1Hz / nhiễu 0.44m; encoder cần GPU (trễ cao).
- Margin offline khiêm tốn (bản pooled hơn identity 4%) → mức **report/workshop**, không phải SOTA.

<!-- Nêu thẳng confound — nó CỦNG CỐ luận điểm "gap ở control, không ở representation". -->

---

## Hướng phát triển

1. **Retrain có RECOVERY DATA** (fix gốc): thu cảnh lệch→về → hết panic ở cos-dropout.
2. **3DGS sim:** closed-loop trong nhà, kiểm soát heading/lighting, lặp ban đêm.
3. **Đo bền hơn:** seq-matching (SeqSLAM) / reachability head kiểu ViNG (thay cosine tức thời).
4. **RTK GPS** (1–2cm): pop chính-xác-mét + ground-truth cho báo cáo.

---

## Kết luận

- **Đánh giá đầu tiên họ V-JEPA 2 trên robot di động.**
- **Offline:** biểu diễn đóng băng **đủ tốt** — AC predictor thắng identity ổn định (**0.744**),
  **transfer chéo-servo có lợi** (0.65 vs 1.073), localize **~2.1m**.
- **Closed-loop:** bung ở **cos-dropout** vì **thiếu lateral-recovery** — *negative finding trung thực.*

> **Gap nằm ở nav-robustness + control + dữ liệu recovery — KHÔNG ở chất lượng representation.**

### Cảm ơn — Q&A

<!--
Chuẩn bị trả lời:
- "Sao không chạy được?" → cos-dropout + no-recovery data (slide 14–15), không phải encoder.
- "0.744 nghĩa là gì?" → hơn baseline đứng-yên 26% trên 2000 window, split cố định.
- "Số closed-loop?" → trung thực: ~10 run, 1 env, 0 về đích; đóng góp là CƠ CHẾ, không phải tỉ lệ.
- "Fix thế nào?" → recovery data + 3DGS sim (slide 17).
-->
