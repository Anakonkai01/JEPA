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

### Teach & Repeat bằng ảnh-mục-tiêu · Đánh giá Offline · Open-loop · Closed-loop

**[Họ tên] — [MSSV]**
Báo cáo cuối kỳ — [Môn Computer Vision] — [GVHD] · 2026-06

<!--
Mở bài: "Em đóng băng encoder video V-JEPA 2.1 làm world model để xe RC LẶP LẠI một tuyến đã được dạy
(teach & repeat) bằng ảnh-mục-tiêu. Trình bày theo 3 tầng: dynamics offline tốt; planner open-loop chọn
joint cả lái lẫn ga khớp người (~94% lái, ga tự chọn); closed-loop thật bộc lộ 3 giới hạn — phân tích kỹ."
-->

---

## Bài toán & Động lực

- **Teach & Repeat:** người lái tay đi hết tuyến 1 lần (*teach*) → lưu chuỗi ảnh-mốc; xe **lặp lại** tuyến
  bằng cách bám từng ảnh-mốc (*repeat*).
- **Không** dựng bản đồ hình học toàn cục, **không** né vật cản (cố ý, để vừa deadline).
- **Vì sao V-JEPA 2.1:** học bằng *feature prediction* (không reconstruct pixel); ViT-L 384 + Dense
  Predictive Loss → đặc trưng patch tốt. Meta chứng minh **V-JEPA 2-AC** planning **trên cánh tay robot**.
- **Câu hỏi của em:** biểu diễn này có dùng được cho **robot DI ĐỘNG ngoài trời** không?

---

## Phần cứng & cách thu data (mô tả trước kiến trúc)

- **Xe RC** + **ESP32-S3**: servo lái TowerPro MG946R (PWM 1000–2000µs) + ESC Hobbywing 8BL150.
- **Điện thoại onboard** (Samsung A42) = camera ultrawide + máy ghi; đọc ESP32 qua **USB**; frame + telemetry
  **chung 1 đồng hồ** → hết lệch clock. *(Trước đó dùng link video 5.8GHz nhưng vỡ ở tầm xa → pivot.)*
- **Lái tay** bằng FlySky i-BUS; `recorder.py` ghi thụ động; `sync.py` ghép frame↔action (chỉnh δ_cam≈100ms).
- **2 domain servo** (KDS cũ / TowerPro mới) → gắn `domain_id` vào model.
- **GPS ~1Hz, nhiễu 0.44m** → chỉ làm cổng pop ảnh-mốc, không giữ làn theo mét.

---

## Dữ liệu & Thống kê (quét lại từ `data/raw_*`)

| Tập | session | frame | thời lượng |
|---|---:|---:|---:|
| KDS | 28 | 53,076 | 1.73 h |
| TowerPro | 181 | 175,435 | 5.71 h |
| **TỔNG** | **209** | **228,511** | **7.43 h** |

- Throttle median **0.084** · đứng-yên (speed<0.06) **11.3%** · 13,871 sự kiện quẹo · speed median 1.05 m/s.
- KDS throttle **~hằng** → thu thêm TowerPro **throttle biến thiên** để học chiều ga.
- *(5 biểu đồ: steer/throttle/speed/độ-dài-session/giờ — `scripts/dataset_stats.py`)*

![h:230](figures/fig_data_throttle_hist.png)

---

## Encoder V-JEPA 2.1 — một phát hiện CV (đo lại)

- Encode **từng frame** → **576 patch token × 1024-D**, encoder **đóng băng tuyệt đối**.
- Pre-encode offline → train đọc latent (~50–100× nhanh).
- **Latent có mã hoá tốc độ không?** Đo lại bằng ridge (fit train / R² val):
  **R²(speed) = +0.30 held-out** → latent mang tín hiệu tốc độ **YẾU** (~30% phương sai), nhiều khả năng
  qua **motion-blur/bối cảnh**, không phải vận tốc thật (image-path, tubelet=1).
- ⚠️ **Đính chính:** ghi chú cũ "R²=−1.1 / mù vận tốc hoàn toàn" **SAI** — không tái lập được.
- → vẫn **bơm tốc độ qua STATE token** (GPS) cho chắc.

---

## AC Predictor (đóng góp chính) — **39.2M tham số**

- Mỗi frame: nhóm token `[action, state, patch×576]`; transformer **block-causal** dự đoán patch map frame kế.
- **Đếm trực tiếp từ checkpoint = 39,192,576 ≈ 39.2M** (chỉ predictor; encoder đóng băng không tính).
  - 12 lớp Transformer × 3.15M = **37.8M (96.5%)** + embed/head/pos ≈ 1.4M.
  - ⚠️ Bản nháp cũ ghi "26M" — **SAI**, đã đếm lại.
- **Kiến trúc tham khảo từ V-JEPA 2-AC** (không gọi "port trung thực"): GIỐNG = encoder frozen + interleave
  + block-causal; KHÁC (có lý do) = state IMU 12-D thay pose 7-D, action 3-D + `domain_id`, pos-emb học được,
  12 lớp thay ~24 (data ít → tránh overfit), động học **bicycle-model** thay tay máy.

---

## Vì sao KHÔNG dự đoán toàn bộ next-state 12-D

- Predictor là **visual-latent predictor** — dự đoán **patch map**, không có head cho 12-D state.
- **IMU rất nhiễu** (rung khung/xóc/mount; GPS 1Hz nội suy; rotvec yaw drift) → dự đoán full state dễ
  **học sai/overfit** với data ít.
- Planning **chỉ cần speed + yaw** → đã do **bicycle-model** lo (fit từ data), không cần predictor đoán lại.
- Cố đoán full state rồi feed lại → **sai số nổ nhanh hơn**.
- → triết lý **"dự đoán ít nhưng phần nào còn tin được"**. *(Tương lai: thay IMU bằng **BNO055** → state sạch.)*

---

# TẦNG 1 — Dynamics offline ✅

---

## Tầng 1 (a): thắng baseline "đứng yên" ổn định

- Metric quyết định = **rollout@k / identity** (<1 = thắng "đoán y hệt frame trước").
- **cd4 (deploy):** @1/@2/@3 = **0.744 / 0.703 / 0.697** — thắng mọi horizon.
- val loss đơn lẻ **bị lừa** (collapse) → phải dùng ratio + action-sensitivity.

---

## Tầng 1 (b): **Cross-domain transfer** ⭐

- Train **chỉ TowerPro** → eval TowerPro = **1.073** (THUA identity!).
- Train **trộn KDS+TowerPro** → eval TowerPro = **0.65**.
- → dữ liệu servo-khác **giúp** học động học chung; `domain_id` cho phép trộn mà không lẫn ánh xạ lệnh→góc.

---

## Tầng 1 (c): độ nhạy hành động — CẢ lái lẫn ga

| `probe_energy` (300 window VAL) | Lái | Ga |
|---|---|---|
| argmin-E **đúng dấu** | **96%** (98/102) | **81%** muốn tiến |
| **contrast** | **0.413** | **0.298** |
| model "muốn" | — | ga +0.094 (≈ data 0.084) |

- Đáy năng lượng **rõ và đúng phía** ở cả 2 trục → CEM đọc được.
- Contrast **tụt theo cự-ly target** (d2 0.44 → d8 0.27) → mốc gần + dạy dày.

![h:220](figures/fig_energy_landscape.png)

---

# TẦNG 2 — Planner open-loop ✅

---

## Planner chọn JOINT (lái + ga) khớp người lái

- **Open-loop:** video chạy theo người lái thật; mỗi frame, model **đề xuất** (lái, ga) — quét **lưới 2-D
  (15 lái × 9 ga)**, chọn đáy năng lượng. (Không phải "xe tự lái".)
- **Lái: sign-turn = 841/893 = 94.2%** (3 session VAL best); |Δsteer| med ~0.07.
- **Ga: model TỰ chọn muốn-tiến 91.9%**, ga med **+0.075** ≈ người **+0.090** → không cần ga=teacher.
- → **năng lực lập kế hoạch (cả lái lẫn ga) LÀNH**; cái gãy ở Tầng 3 KHÔNG phải "planner dốt".
- *(Demo web :8070 — landscape **2-D lái×ga**: ● người vs ✕ model. `demo_precompute.py`+`demo_web.py`, export MP4.)*

---

# TẦNG 3 — Closed-loop ngoài trời ❌

---

## Teach & Repeat thật: bám nửa đầu rồi bung

- *Teach:* lái tay, chụp chuỗi ảnh-mốc + GPS (~15m). *Repeat:* phone→PC (V-JEPA→AC→CEM)→ESP32.
- **Pattern bất biến:** bám tốt tới ~giữa route (lệch <0.5m) → tới mốc "yếu" → **bung ra lề**.
- Chỉnh tham số chỉ **dời điểm bung, không xoá** → giới hạn model/data/descriptor, không phải tham số.
- ~10 run, 1 môi trường, **0 run về đích** → kết quả **định tính + cơ chế**.

---

## Bung vì **3 nguyên nhân** (không phải 1)

- **A — Descriptor không bất-biến-sáng:** ảnh-mốc lúc dạy ≠ lúc chạy → cosine tụt <0.1 → goal không phân
  biệt được → energy phẳng → lái loạn. *(probe: ảnh đúng rơi hạng 41 khi sáng-xa.)*
- **B — Đứng-yên (KHÔNG phải OOD):** ga thấp → speed=0 → `yaw=k·steer·speed=0` → landscape phẳng. *(ablation
  ép speed=0: contrast 0.41→0.11 mà không đổi cảnh; live ga≥0.07 → 0.2–0.57.)* → **sàn ga TMIN=0.07**.
- **C — Thiếu recovery data:** dạy giữa-line → không ảnh nào dạy "lệch 2m bẻ về đâu" → đâm lề.

---

## Đính chính & bài học phương pháp

| Từng nói | Đo lại → đúng |
|---|---|
| "26M tham số" | **39.2M** (đếm checkpoint) |
| "Model OOD ở park" | **Đứng-yên** làm phẳng, không OOD |
| "R²(speed)=−1.1, mù vận tốc" | **+0.30** held-out — yếu, không mù |
| "geosteer sửa trôi ngang" | DIVERGE (rotvec yaw drift) |

- Bài học: **đếm/đo trực tiếp**, so **cùng hệ đo**, **tách confound** thay vì gộp 1 nhãn.

---

## So với Meta & ViNG

- **Meta (tay máy):** cảnh bàn cố định, không heading/ánh-sáng/lệch-ngang; "chính xác cm" = proprioception
  tay máy (**khác hệ đo**).
- **Xe ngoài trời:** action đổi-cảnh nhỏ + cos-dropout + đứng-yên + no-recovery → **khó hơn**.
- **ViNG chạy được** vì policy **train trên data CÓ recovery**; data dạy-1-lượt của em thiếu tín hiệu đó.
- *(Đồ-thị-ảnh topological: chỉ thử nhanh, không dùng chính — zigzag / ảnh dạy≠chạy / mốc xa / GPS thô → khó debug.)*

---

## Hạn chế

- Closed-loop: 1 môi trường, 0 về đích, không success-rate metric → định tính.
- Thiếu recovery data; descriptor nhạy ánh sáng; GPS 1Hz; **IMU điện thoại nhiễu** (chỉ tin speed+yaw).
- Encoder cần GPU → qua PC, trễ CEM 0.5–5.5s/tick.
- Margin offline **khiêm tốn** → mức report/workshop, không SOTA.

---

## Hướng phát triển

1. **Thay IMU bằng BNO055** (sensor-fusion phần cứng) → state token sạch hơn nhiều.
2. **Recovery data / augment** (fix nguyên nhân C).
3. **Learned lighting-invariant descriptor** trên frozen V-JEPA (fix nguyên nhân A).
4. **3DGS sim** để test closed-loop trong nhà; **RTK GPS** cho định vị cm.

---

## Kết luận

- Frozen V-JEPA 2.1 → AC predictor **39.2M** **thắng baseline ổn định**, nhạy **cả lái lẫn ga**,
  **transfer chéo-domain**; planner **open-loop chọn joint lái+ga khớp người** (~94% lái, ga tự chọn muốn-tiến 92%).
- Closed-loop **bung** do **3 nguyên nhân**: descriptor-ánh-sáng + đứng-yên + thiếu-recovery — **KHÔNG ở
  chất lượng biểu diễn**.
- **Đánh giá đầu tiên họ V-JEPA 2 trên robot di động** + **negative finding trung thực, có cơ chế, đã đính chính**.

### Cảm ơn — Q&A
