# Calibrate Servo

## HIỆN TẠI — TowerPro MG946R (đổi 2026-06-06, từ KDS N680 HV)

⚠️ **MG946R là servo analog chuẩn 4.8–6.0V (tối đa ~6.6V) — KHÔNG phải HV.**
Cấp servo **≤6V**, TUYỆT ĐỐI không 7.4/8.4V (cháy servo).

Calibrate bằng **JOG** (`firmware/src/servo_calibrate.cpp`, env `servocal`) — nudge ∓10/∓1µs tới khi
lốp vừa chạm khung rồi mark, không dính sai số phản xạ:

| Mục | Giá trị |
| --- | --- |
| Biên cơ khí TRÁI (L) | 1120 µs |
| Biên cơ khí PHẢI (R) | ≥2000 µs (chạm trần phần mềm 2000 của tool — thực tế ≥2000) |
| TÂM (C, bánh thẳng) | 1500 µs (lệch +0) |
| **Clamp firmware** `SERVO_MIN/CENTER/MAX` | **1150 / 1500 / 1850 µs** — GIỮ NGUYÊN |

→ Clamp `[1150,1850]` nằm GỌN trong biên cơ khí `[1120, ≥2000]` (margin trái 30µs, phải ≥150µs)
→ **AN TOÀN, không stall hai đầu.** Giữ nguyên clamp = khớp 29 session data cũ (action→góc tĩnh không đổi).

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
