# Calibrate Servo

## HIỆN TẠI — TowerPro MG946R (đổi 2026-06-06, từ KDS N680 HV)

⚠️ **MG946R là servo analog chuẩn 4.8–6.0V (tối đa ~6.6V) — KHÔNG phải HV.**
Cấp servo **≤6V**, TUYỆT ĐỐI không 7.4/8.4V (cháy servo).

Calibrate bằng **JOG** (`firmware/src/servo_calibrate.cpp`, env `servocal`) — nudge ∓10/∓1µs tới khi
lốp vừa chạm khung rồi mark, không dính sai số phản xạ:

**Recalib 2026-06-07 (full range, tâm +60):**

| Mục | Giá trị |
| --- | --- |
| Biên cơ khí TRÁI (L) | 1000 µs (full lock) |
| Biên cơ khí PHẢI (R) | 2000 µs (full lock) |
| TÂM (C, bánh thẳng) | 1560 µs (lệch +60 so với 1500) |
| **Firmware** `SERVO_MIN/CENTER/MAX` | **1000 / 1560 / 2000 µs** |

→ Mở full dải cơ khí `[1000, 2000]` (clamp mềm 1150/1850 cũ chỉ cần cho KDS yếu — TowerPro
  chịu hết cữ êm). `driveNorm` **pivot quanh CENTER**: trái 1000↔1560 (560µs), phải 1560↔2000
  (440µs) — gain stick hai bên khác nhau nhưng **góc lái cơ khí đối xứng** (full lock hai đầu).
  Neutral = steer=0 = 1560 → không giật.

⚠️ **Action→góc KHÔNG còn khớp 29 session data cũ** (cũ: KDS, C1500, dải 1150–1850). Cũ vs mới
  là **2 domain khác nhau** cho phần action-conditioned (AC Predictor/LeWM) — đừng trộn; data
  cũ vẫn dùng chung được cho phần thị giác (frozen V-JEPA không quan tâm action). Lô cũ đã up Drive.

> Lưu ý data: MG946R chậm hơn KDS digital (~0.17–0.2s/60°, analog) → đáp ứng lái khi giật nhanh
> (transient) trễ hơn data cũ. Góc tĩnh khớp, chỉ transient lệch nhẹ — chấp nhận được, giảm trọng
> data cũ nếu cần.

---

## LỊCH SỬ — KDS N680 HV (servo cũ, đã thay)

> Chạy HV tới 8.4V. Thay vì yếu/lỗi (sụt mô-men, giật khi có tải).
> Calibrate cũ (scan + bấm ENTER, trung bình 5 hiệp):

```text
=======================================================
             BẢNG TỔNG HỢP DỮ LIỆU THỰC NGHIỆM
=======================================================
  Hiệp Số  |   Max Left (us)   |   Max Right (us)
-------------------------------------------------------
     1     |      1140 us      |      1875 us
     2     |      1130 us      |      1890 us
     3     |      1125 us      |      1890 us
     4     |      1125 us      |      1890 us
     5     |      1140 us      |      1905 us
-------------------------------------------------------
👉 KẾT LUẬN GÓC KHÓA CŨ: [1142 us <--> 1880 us]
=======================================================
```
