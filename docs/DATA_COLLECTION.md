# DATA_COLLECTION.md — Kịch bản thu data huấn luyện (world model)

> Mục tiêu: thu data cho **AC Predictor** (V-JEPA latent: `s_t + action_t → ŝ_{t+1}`).
> Chất lượng data = **độ phủ và độ tách (decorrelation) của action**, KHÔNG phải lái cho đẹp.

## Bối cảnh (2026-06-06)

- 29 session cũ (~55k frame): **steering phong phú nhưng throttle gần như hằng số ~7.5%**
  (lúc thu đẩy full @ dual rate 7-8%) → model chỉ học được dynamics ở ~1 tốc độ.
- **Dual rate throttle nâng lên 14-15%.** Việc này KHÔNG phá data cũ: action ghi lại map
  thẳng sang ESC qua firmware (`esc_us = 1000+(throt+1)/2*1000`), độc lập dual rate; dual rate
  chỉ **mở rộng tầm action với tới** (cũ ≤ ~0.075, giờ tới ~0.15). Data cũ là **tập con** của
  tầm mới → giữ nguyên, data mới **phủ thêm vùng ga cao + biến thiên ga**.
- Servo mới đã calibrate: clamp `[1150,1850]` giữ nguyên, tâm 1500 = thẳng (xem `firmware/specs.md`).

### Vùng throttle khả dụng (phần cứng này)
| Action ga | ESC % | Trạng thái |
|-----------|-------|-----------|
| `0` | 0% | Dừng / coast (nhả ga) |
| `0.01–0.05` | 1–5% | ⚠️ **VÙNG CHẾT** — xe stall không lăn, motor/ESC nóng → **TRÁNH ở lì đây** |
| `~0.06–0.07` | 6–7% | Chậm (vừa qua sàn) |
| `~0.10` | 10% | Trung bình |
| `~0.15` | 15% | Nhanh (full mới, vẫn kiểm soát được) |

→ Khi lái: ga **hoặc OFF (0, coast)** **hoặc trong [6%, 15%]**. Đừng giữ ở vùng chết 1–5%.

---

## Luật chung (MỌI session)

- **Mode:** CH9 = RECORD; CH10 bật/tắt ghi. Phone cắm cổng native (auto-REC theo CH10).
- **CỐ ĐỊNH từ giờ — không đổi giữa các session:** dual rate (14-15%), trim lái (đã căn thẳng),
  EPA. Đổi giữa chừng = action mang nghĩa khác giữa các buổi = **lệch dataset**.
- **Fast shutter ON** (chống nhòe). Tránh nắng gắt chiếu thẳng (cháy sáng/exposure xấu).
- **Đa dạng cảnh:** mỗi buổi đổi địa điểm/hướng nắng/nền (cỏ, bê tông, vật cản…). Scene đa dạng
  quan trọng cho world model + tạo goal-state cho CEM sau này.
- **Session ngắn, nhiều buổi** (~2–4 phút/session) > vài buổi dài. Dễ đa dạng + dễ bỏ buổi lỗi.
- **Giữ ~10–15% frame ĐỨNG YÊN (ga=0):** dừng/nhả ga xen kẽ → cho model tương phản "đứng vs chạy"
  (nếu thiếu, model coi "luôn trôi tới" là mặc định → action throttle vô nghĩa khi plan).

---

## 5 kịch bản

### S1 — Thang throttle (đi thẳng, tách ga) 🔑 mới
- Đi **gần thẳng** (chỉ chỉnh lái nhỏ), bước ga: `6% → 10% → 15% → nhả (coast) → dừng`, mỗi mức
  giữ ~2–3s. Lặp lên/xuống thang nhiều lần.
- **Dạy:** ga → tốc độ trôi ở **nhiều mức** + pha tăng tốc/giảm tốc/coast. Đây là cái 29 session cũ thiếu.

### S2 — Stop-and-go / nhồi ga ngắt quãng
- Từ đứng yên → **punch ga** lên một mức → nhả → **coast tới dừng** → lặp, đổi mức punch mỗi lần.
- **Dạy:** tương phản ga on/off mạnh, động học tăng tốc & coast (giảm tốc), **nhiều frame ga=0**.

### S3 — Quét lái ở tốc độ cố định (tách steering)
- Giữ **một mức ga ổn định**, quét lái `full-trái ↔ tâm ↔ full-phải` (êm rồi gắt): slalom, S, vòng
  tròn cả 2 chiều. **Lặp ở 2–3 mức ga khác nhau** (chậm / trung bình / nhanh) qua các lần.
- **Dạy:** lái → xoay-cảnh; phủ hết tầm lái. Lặp ở nhiều tốc độ để **tách lái khỏi tốc độ**.

### S4 — Phối hợp lái + ga cùng lúc
- Vừa cua vừa tăng tốc; vừa cua vừa nhả/giảm tốc; **cố tình trộn ngược** (cua gắt khi nhanh, cua
  rộng khi chậm) để **phá tương quan** "nhanh=thẳng, chậm=cua". Số 8 có đổi tốc độ.
- **Dạy:** động học khớp steering×throttle; decorrelation (quan trọng để planner tách được 2 trục).

### S5 — Chạy tự do / kiểu goal (đa dạng cảnh)
- Lái tự nhiên qua nhiều môi trường; **tiến tới một mốc/vật rồi dừng sát** (các state này = giống
  goal-image cho CEM eval). Có vật cản, lối đi, landmark rõ.
- **Dạy:** phân bố thực tế + đa dạng scene + state "tới đích rồi dừng".

### (Tùy chọn) S6 — Lùi
- **Chỉ thu nếu planner sẽ dùng lùi.** Nếu nav chỉ tiến → bỏ, khỏi thêm vùng action không xài.

---

## Mục tiêu coverage & tiêu chí dừng

- **Tỉ trọng gợi ý (data mới):** S1 ~20% · S2 ~15% · S3 ~25% · S4 ~25% · S5 ~15%.
- **Tiêu chí dừng (theo phân bố, tốt hơn đếm buổi):** ghép data cũ+mới, vẽ histogram throttle —
  **không mức ga nào chiếm > ~40%** số frame đang-chạy; có **~10–15% frame ga=0**; tầm `[0.06, 0.15]`
  được phủ liên tục (không chỉ đóng cục ở 0.075).
- **Ballpark:** ~**15–25 session mới** (2–4 phút) thường đủ. Ưu tiên vùng cũ THIẾU: ga cao (0.10–0.15)
  và ga chậm sát sàn (0.06–0.07), + nhiều stop/go.
- Steering data cũ đã đủ → buổi mới vẫn quét lái nhưng **trọng tâm là throttle + phối hợp (S1/S2/S4)**.

## Tránh

- ❌ Luôn ghép **một tốc độ với một kiểu maneuver** (vd full ga chỉ khi thẳng) → model lẫn lái với tốc độ.
- ❌ Đường thẳng full-ga dài lê thê (ít transition, ít thông tin) — đổi action thường xuyên hơn.
- ❌ Ở lì **vùng chết 1–5%** (stall, nóng motor/ESC) — ga hoặc 0 hoặc ≥6%.
- ❌ Frame nhòe (chạy ẩu), cháy nắng, xe tì vào vật cản đứng im, lái giật làm hỏng sync.
- ❌ **Đổi trim/EPA/dual rate giữa chừng.**

## Sau khi thu

- Chạy `src/sync.py` → `actions_synced.csv` + `imu_synced.csv` mỗi session (offset 0 cho data mới).
- Chuẩn hóa action **PER-DIM theo biên THỰC đo từ data** (đừng hardcode ±0.15) — steering và throttle
  tách riêng, để tín hiệu throttle nhỏ không bị steering át.
- Cân nhắc **subsample/giảm trọng** cụm spike 0.075 của data cũ nếu histogram lệch mạnh về đó.
