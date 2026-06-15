---
marp: true
theme: default
paginate: true
size: 16:9
header: 'World Model (V-JEPA 2.1) cho Xe RC — Teach & Repeat'
footer: '[Họ tên] · [Lớp/Môn CV] · 2026-06'
---

<!--
RENDER: VS Code "Marp for VS Code" → Export PDF/PPTX; hoặc `npx @marp-team/marp-cli 3_SLIDES.md -o slides.pdf`.
Mỗi `---` = 1 slide. Khối <!-- --> = speaker notes. Thời lượng ~13–16 phút + Q&A.
Cấu trúc: phần cứng & data TRƯỚC → kiến trúc → 3 tầng kết quả (offline → open-loop → closed-loop).
Mọi số tái lập được bằng script trong repo (xem 2_REPORT_FULL.md §Phụ lục).
-->

# World Model Hành-động-điều-kiện dựa trên **V-JEPA 2.1** cho Xe RC

### Teach & Repeat bằng ảnh-mục-tiêu · Offline · Open-loop · Closed-loop

**[Họ tên] — [MSSV]**
Báo cáo cuối kỳ — [Môn Computer Vision] — [GVHD] · 2026-06

<!--
Mở bài: "Em đóng băng encoder video V-JEPA 2.1 làm world model để xe RC LẶP LẠI một tuyến đã được dạy
(teach & repeat) bằng ảnh-mục-tiêu. Trình bày 3 tầng: dynamics offline; planner open-loop chọn joint
cả lái lẫn ga khớp người (~94% lái); closed-loop thật bộc lộ giới hạn ở khâu định-vị + điều khiển."
-->

---

## Bài toán & Động lực

- **Teach & Repeat:** người lái tay đi hết tuyến 1 lần (*teach*) → lưu chuỗi ảnh-mốc; xe **lặp lại**
  tuyến bằng cách bám từng ảnh-mốc (*repeat*). Không dựng bản đồ hình học toàn cục.
- **Vì sao V-JEPA 2.1:** học bằng *feature prediction* (không reconstruct pixel); ViT-L 384 + Dense
  Predictive Loss → đặc trưng patch tốt. Meta chứng minh **V-JEPA 2-AC** planning **trên cánh tay robot**.
- **Câu hỏi của em:** biểu diễn này có dùng được cho **robot DI ĐỘNG ngoài trời** không?
- **Hai tầng tách bạch:** *định-vị* (thị giác + GPS) vs *điều khiển* (AC predictor + CEM) — để quy
  trách nhiệm rõ khi phân tích lỗi.

---

## Khái niệm & thước đo (định nghĩa trước khi dùng)

- **Latent:** mỗi ảnh → **576 token × 1024-D** (qua V-JEPA).
- **rollout@k / identity:** sai số dự đoán k bước của model ÷ sai số của baseline "đoán cảnh không
  đổi". **<1 = tốt hơn 'đứng yên'** (điều kiện *cần*, chưa *đủ*).
- **Năng lượng** `E = ‖ẑ − z_goal‖₁` (L1 latent dự đoán cuối ↔ latent mục-tiêu). E thấp = action tốt.
- **Contrast** `= (E_max−E_min)/E_min` khi quét 1 trục: cao = đáy rõ; ~0 = **landscape phẳng** (mất tín hiệu).
- **Sign-turn:** trên frame đang quẹo (|lái|>0.15), tỉ lệ **dấu** lái model trùng dấu lái người.
- **Open-loop:** model chỉ ĐỀ XUẤT (video chạy theo người) · **Closed-loop:** model THỰC SỰ lái.

---

## Phần cứng & cách thu data (mô tả trước kiến trúc)

- **Xe RC + ESP32-S3**: servo lái TowerPro MG946R (PWM 1000–2000µs) + ESC Hobbywing 8BL150.
- **Điện thoại onboard** (Samsung A42) = camera ultrawide + máy ghi; đọc ESP32 qua **USB**; frame +
  telemetry **chung 1 đồng hồ** → hết lệch clock. *(Trước đó dùng link video 5.8GHz nhưng vỡ ở tầm xa → pivot.)*
- **Đồng bộ:** nội suy telemetry 50Hz tại đúng thời điểm cảnh mỗi frame (chỉnh δ_cam≈100ms) → loại
  frame mất gói → mỗi frame ⇒ (ảnh, action 3-D, state 12-D) → chia **session 80/20 = 167 train / 42 val**.
- **2 domain servo:** servo KDS cũ **hỏng → thay TowerPro** → 2 ánh xạ lệnh→góc → gắn `domain_id`.

![h:240](figures/fig_data_pipeline.png)

---

## Dữ liệu & Thống kê (quét lại từ `data/raw_*`)

| Tập | session | frame | thời lượng |
|---|---:|---:|---:|
| KDS | 28 | 53,076 | 1.73 h |
| TowerPro | 181 | 175,435 | 5.71 h |
| **TỔNG** | **209** | **228,511** | **7.43 h** |

- Throttle median **0.084** · đứng-yên **11.3%** · **13,871 sự kiện quẹo** · speed median 1.05 m/s.
- Lái tay dao động hai phía liên tục → **data CÓ hành vi điều-chỉnh/sửa-lệch** (quan trọng cho §closed-loop).

![h:215](figures/fig_data_steer_timeseries.png)

---

## Encoder V-JEPA 2.1 + pipeline pre-encode

- Encode **từng frame** → **576 patch token × 1024-D**, encoder **đóng băng tuyệt đối**.
- **Pre-encode offline 1 lần** → lưu latent fp16 → huấn luyện chỉ đọc latent (**~50–100× nhanh**).
- Giữ patch map đầy đủ (không pool) cho thông tin không gian; 384px = độ phân giải gốc checkpoint (chất lượng).

![h:250](figures/fig_encoder_pipeline.png)

---

## AC Predictor (đóng góp chính) — **≈ 39.2M tham số**

- Mỗi frame: nhóm token `[action(3) · state(12) · patch×576]`; transformer **block-causal** dự đoán
  patch map frame kế.
- **Đếm trực tiếp từ checkpoint = 39,192,576 ≈ 39.2M** (chỉ predictor; encoder đóng băng không tính;
  12 lớp Transformer ~96%).

![h:250](figures/fig_arch_ours.png)

---

## Kiến trúc tham khảo từ V-JEPA 2-AC — giống / khác

| | Meta (tay máy) | Của em (xe) |
|---|---|---|
| State | pose 7-D (proprioception) | IMU + prev-action **12-D** |
| Action | Δ end-effector 7-D | [steer, throttle, **domain_id**] 3-D |
| Pos-emb | 3D-RoPE | học được |
| Quy mô | ~24 lớp / ~300M | **12 lớp / 39.2M** (data ít → tránh overfit) |
| Động học | tay máy | **bicycle-model** fit từ data xe |

![h:200](figures/fig_arch_meta.png)

---

# TẦNG 1 — Dynamics offline

---

## Tầng 1 (a): dự đoán tốt hơn baseline "đứng yên"

- **cd4 (deploy):** rollout@1/2/3 / identity = **0.744 / 0.703 / 0.697** — <1 ở mọi horizon.
- **Diễn giải đúng mức:** thắng identity chỉ **xác nhận model học được action-conditioned dynamics**
  (dự đoán tốt hơn "cảnh đứng yên") — điều kiện *cần, chưa đủ*. Không tự nó = "lái được".
- val loss đơn lẻ **bị lừa** (collapse) → phải dùng tỉ số + action-sensitivity.

---

## Tầng 1 (b): **Transfer chéo-domain-servo** ⭐

- Train **chỉ TowerPro** → eval TowerPro = **1.073** (THUA identity!).
- Train **trộn KDS+TowerPro** → eval TowerPro = **0.65**.
- → dữ liệu servo-khác **giúp** học động học chung; `domain_id` cho phép trộn mà không lẫn ánh xạ.
- ("Quả ngọt ngoài ý muốn" của việc servo KDS hỏng phải thay.)

![h:235](figures/fig_transfer.png)

---

## Tầng 1 (c): độ nhạy hành động — đo RIÊNG từng trục trước

| `probe_energy` (300 window quẹo VAL) | Lái | Ga |
|---|---|---|
| argmin-E **đúng dấu** | **95%** (285/300) | **83%** muốn tiến |
| **contrast** (trên frame quẹo) | **0.33** | **0.27** |
| model "muốn" | — | ga +0.11 (≈ data 0.084) |

- Đáy năng lượng **rõ và đúng phía** ở cả 2 trục → CEM đọc được. *(đo riêng để cô lập, joint ở Tầng 2.)*

![h:215](figures/fig_energy_landscape.png)

---

# TẦNG 2 — Planner open-loop (JOINT lái×ga)

---

## Planner chọn JOINT (lái + ga) khớp người lái

- **Thuật toán (open-loop):** mỗi frame thật, goal = mốc d=4 (~0.9s) phía trước; quét **lưới 2-D
  (15 lái × 9 ga = 135)**; mỗi tổ hợp roll qua AC predictor → E; **argmin chọn cả lái lẫn ga**.
- **Lái: sign-turn = 841/893 = 94.2%** (3 session VAL); ga: model **tự chọn muốn-tiến 91.9%** (med
  +0.075 ≈ người +0.090); contrast joint ~0.52.
- → **năng lực lập kế hoạch (cả lái lẫn ga) LÀNH**; cái gãy ở Tầng 3 KHÔNG phải "planner dốt".
- **⚠ KHÔNG phải "xe tự lái"** — video chạy theo người, model chỉ đề xuất.

---

# TẦNG 3 — Closed-loop ngoài trời (kết quả âm)

---

## Teach & Repeat thật: bám nửa đầu rồi bung

- *Teach:* lái tay, chụp chuỗi ảnh-mốc + GPS (~15m). *Repeat:* phone→PC (V-JEPA→AC→CEM)→ESP32.
- **Pattern bất biến:** bám tốt tới ~giữa route (lệch <0.5m) → tới mốc "yếu" → **bung ra lề**.
- Chỉnh tham số chỉ **dời điểm bung, không xoá** → giới hạn ở khâu định-vị/điều-khiển, không phải tham số.
- ~10 run, 1 môi trường, **0 run về đích** → kết quả **định tính + cơ chế**.

---

## Bung vì **2 nguyên nhân** (khâu định-vị + điều khiển)

- **A — Descriptor ĐỊNH-VỊ không bất-biến (KHÔNG phải "V-JEPA hỏng"):** khâu *pop ảnh-mốc* dùng
  **cosine trên latent mean-pool** → đổi sáng/heading → ảnh-đúng rơi **hạng 41** (top1 0–3%) → goal
  không phân biệt → lái loạn. *(Khâu điều khiển dùng **patch-L1** vẫn BỀN <5%; SeqSLAM/multi-ref không cứu.)*
- **B — Vùng-chết đứng-yên (cơ chế động học, ĐÃ vá):** `yaw=k·steer·speed` → speed=0 ⇒ landscape phẳng.
  Ablation ép xe đứng-yên (cùng cảnh): contrast E(steer) **0.335 (chạy) → 0.088 (đứng yên, ×3.8)** →
  **fix = sàn ga TMIN=0.07**.

---

## Đính chính & bài học phương pháp

| Từng nói | Đo lại → đúng |
|---|---|
| "26M tham số" | **39.2M** (đếm checkpoint) |
| "contrast lái 0.41" | **0.33 trên frame quẹo** (0.41 là all-frame) |

- Bài học: **đếm/đo trực tiếp** bằng script · so **cùng hệ đo** · **tách confound** (đứng-yên vs định-vị)
  thay vì gộp một nhãn mơ hồ.

---

## So với Meta & ViNG

- **Meta (tay máy):** cảnh bàn cố định, không heading/ánh-sáng/lệch-ngang; "chính xác cm" =
  proprioception tay máy (**khác hệ đo**).
- **Xe ngoài trời:** action đổi-cảnh nhỏ + cosine-định-vị-dropout + đứng-yên → **khó hơn** về robustness.
- **ViNG chạy được** vì policy đa dạng + **không** dựa cosine-pooled cho định-vị như khâu pop của em.

---

## Hạn chế & Hướng phát triển

**Hạn chế:** closed-loop 1 môi trường / 0 về đích (định tính); descriptor định-vị nhạy sáng/heading;
GPS 1Hz; IMU điện thoại nhiễu (chỉ tin speed+yaw); encoder cần GPU; margin offline khiêm tốn.

**Hướng phát triển:**
1. **BNO055** (IMU sensor-fusion phần cứng) → state token sạch.
2. **Learned descriptor bất-biến sáng/heading** trên frozen V-JEPA (fix gốc A).
3. **Token-shift augment** (đo offline khuếch đại bẻ-về 3.4–5.4×; proxy, chưa transfer).
4. **3DGS sim** test closed-loop trong nhà; **RTK GPS** định vị cm.

---

## Kết luận

- Frozen V-JEPA 2.1 → AC predictor **39.2M** **dự đoán tốt hơn baseline đứng yên**, nhạy **cả lái lẫn
  ga**, **transfer chéo-domain**; planner **open-loop chọn joint lái+ga khớp người** (~94% lái, ga tự chọn 92%).
- Closed-loop **bung** do **khâu định-vị (descriptor pooled-cosine nhạy sáng/heading)** + **chế-độ-điều-khiển
  (vùng-chết đứng-yên, đã vá)** — **KHÔNG ở chất lượng biểu diễn**.
- **Đánh giá đầu tiên họ V-JEPA 2 trên robot di động** + **kết quả âm có cơ chế, định lượng**.

### Cảm ơn — Q&A
