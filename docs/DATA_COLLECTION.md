# DATA_COLLECTION.md — Kế hoạch thu data world model (trong công viên)

> Mục tiêu: thu data cho world model (`s_t + action_t → ŝ_{t+1}`), dùng cho CẢ
> **vjepa_ac** (V-JEPA 2.1 latent) lẫn **LeWM** (pixel).
> Chất lượng data = **độ phủ + độ tách (decorrelation) của action** và **độ đa dạng cảnh**,
> KHÔNG phải lái cho đẹp. Cập nhật **2026-06-07** (sau khi train xong cả 2 model).

## 🎯 Vì sao thu thêm — bằng chứng ĐO ĐƯỢC từ model (2026-06-07)

Sau khi train + đánh giá rigorous, **giới hạn lớn nhất hiện tại là ĐỘ ĐA DẠNG DATA**, không phải model:

| Đo trên 28 session / 53k frame | Số liệu | Đánh giá |
|---|---|---|
| Steering | full `[-1,+1]`, std 0.45, 37% cua / 63% thẳng | ✅ **đủ** — không cần ưu tiên |
| **Throttle** | `[-0.10, +0.09]`, std **0.05**, 82% tiến / 8% lùi / 11% dừng | ❌ **gần như cố định → GAP CHÍNH** |
| `eff_rank` latent (LeWM) | chỉ **~7–9 / 256** | ❌ latent chỉ ~8 "chiều biến thiên" → cảnh + action quá đơn điệu |

→ Model đã xác nhận: **throttle gần hằng + cảnh ít đa dạng** kéo `eff_rank` xuống. Mẻ data mới phải
**đánh thẳng vào 2 thứ này: (1) biến thiên ga/tốc độ, (2) đa dạng cảnh trong công viên.** Steering đã đủ.

## 🌳 Ràng buộc: CHỈ thu trong công viên — cách tối đa đa dạng *bên trong* 1 công viên

Data cố tình giới hạn trong khu công viên (model + goal sẽ là park-specific — chấp nhận được cho đề tài).
Vì bị giới hạn không gian → phải **chủ động tạo đa dạng** bằng các trục khác:

- **Chia công viên thành 3–5 "khu" có NỀN khác nhau** (cỏ / bê tông / lối sỏi / dưới bóng cây / cạnh
  vật cản–ghế–cột). Thu vài session ở mỗi khu. Nền khác nhau = latent V-JEPA trải rộng hơn (tăng eff_rank).
- **Đổi GIỜ / hướng nắng:** thu cả buổi sáng và xế chiều; lái cả **ngược sáng và xuôi sáng**. Tránh nắng
  gắt giữa trưa (cháy sáng). Bóng đổ khác giờ = thêm đa dạng.
- **Đổi HƯỚNG đi:** cùng một lối nhưng đi cả 2 chiều; vòng cùng chiều và ngược chiều kim đồng hồ.
- **Landmark rõ làm GOAL-state:** gốc cây / ghế / cột / biển báo. Khi kết mỗi đoạn, **tiến tới sát landmark
  rồi DỪNG** — các khung "tới đích" này chính là goal-image cho CEM planning (Phase 4) sau này.

## ⚙️ Bối cảnh phần cứng (giữ nguyên, ĐỪNG đổi giữa các buổi)

- **Dual rate throttle = 14–15%** (đã nâng từ 7–8%). Data cũ (~0.075) là **tập con** của tầm mới → không
  mâu thuẫn; data mới phủ thêm **ga cao (0.10–0.15) + biến thiên ga**.
- Servo MG946R, clamp `[1150,1850]`, tâm 1500 = thẳng (`robot/firmware/specs.md`).
- Frame ~10fps, `dcam_ms` tự khử trễ camera (data mới offset 0).

### Vùng throttle khả dụng
| Action ga | ESC % | Trạng thái |
|---|---|---|
| `0` | 0% | Dừng / coast (nhả ga) — **cần ~10–15% frame ở đây** |
| `0.01–0.05` | 1–5% | ⚠️ **VÙNG CHẾT** — stall, motor/ESC nóng → **TRÁNH ở lì** |
| `0.06–0.07` | 6–7% | Chậm (vừa qua sàn) |
| `0.10` | 10% | Trung bình |
| `0.15` | 15% | Nhanh (full mới, vẫn kiểm soát) |

→ Ga **hoặc = 0 (coast/dừng)** **hoặc trong `[0.06, 0.15]`**. Không giữ lì ở 1–5%.

## ⚠️ Bài học train (ảnh hưởng cách lái)

- **Xe phải DI CHUYỂN THẬT giữa các frame.** Ở 10fps, nếu xe bò quá chậm/đứng creep → 2 frame liên tiếp
  gần giống hệt → world model học "copy frame" (vô dụng). Lái cho cảnh **đổi rõ** giữa các giây; đừng rề rà
  ở vùng chết. (Khi train ta dùng `frame_skip=5` ≈ 0.5s/bước để khuếch đại chuyển động — nhưng data vẫn
  cần xe lăn thật.)
- **Tránh đoạn dài cùng một action** (thẳng đều full ga) → ít transition, ít thông tin. **Đổi action thường xuyên.**

---

## 📋 Luật chung (MỌI session)

- **Mode:** CH9 = RECORD; CH10 bật/tắt ghi (phone cắm cổng native, auto-REC theo CH10).
- **Fast shutter ON** (chống nhòe).
- **CỐ ĐỊNH, không đổi giữa các buổi:** dual rate (14–15%), trim lái, EPA. Đổi giữa chừng = action đổi nghĩa
  giữa các buổi = **lệch dataset** (lỗi nặng nhất).
- **Session ngắn, nhiều buổi** (~2–4 phút) > vài buổi dài (dễ đa dạng + dễ bỏ buổi lỗi).
- **Giữ ~10–15% frame ĐỨNG YÊN (ga=0)** xen kẽ → cho model tương phản "đứng vs chạy".
- Mỗi buổi đổi **khu / hướng nắng / nền** (xem ràng buộc công viên trên).

## 🎬 5 kịch bản (mỗi session làm 1 kịch bản chính)

| | Kịch bản | Làm gì | Dạy model |
|---|---|---|---|
| **S1** 🔑 | **Thang throttle** (đi gần thẳng) | Bước ga `6%→10%→15%→nhả→dừng`, mỗi mức giữ 2–3s, lặp lên/xuống | ga→tốc độ ở **nhiều mức** + tăng/giảm tốc/coast (cái data cũ THIẾU) |
| **S2** 🔑 | **Stop-and-go** | Đứng yên → **punch ga** một mức → nhả → coast tới dừng → lặp, đổi mức punch | tương phản ga on/off, động học tăng tốc & coast, **nhiều frame ga=0** |
| **S3** | **Quét lái ở ga cố định** | Giữ 1 mức ga, quét lái trái↔tâm↔phải (êm→gắt): slalom, S, vòng tròn 2 chiều. **Lặp ở 2–3 mức ga** | lái→xoay-cảnh; **tách lái khỏi tốc độ** |
| **S4** 🔑 | **Phối hợp lái+ga** | Vừa cua vừa tăng tốc / vừa cua vừa giảm; **cố tình trộn ngược** (cua gắt khi nhanh, cua rộng khi chậm); số 8 đổi tốc | decorrelation steering×throttle (planner cần tách 2 trục) |
| **S5** | **Tự do / goal (đa dạng cảnh)** | Lái tự nhiên qua nhiều khu; **tiến tới landmark rồi dừng sát** | phân bố thực + đa dạng scene + state "tới đích" cho CEM |

🔑 = ưu tiên cao (đánh vào gap throttle). **(Tùy chọn S6 — Lùi:** chỉ thu nếu planner sẽ dùng lùi; nav chỉ-tiến thì bỏ.)

## 🗓️ Kế hoạch cụ thể — ~16–20 session mới

Gợi ý phân bổ (xen kẽ khu/giờ để đa dạng cảnh). Mỗi ô = 1 session ~2–4 phút:

| # | Kịch bản | Khu / nền | Ghi chú |
|---|---|---|---|
| 1–4 | **S1 Thang throttle** | mỗi session 1 khu khác (cỏ, bê tông, sỏi, bóng cây) | đi gần thẳng, tập trung biến thiên ga |
| 5–7 | **S2 Stop-and-go** | 3 khu khác nhau | nhiều ga=0, punch đa mức |
| 8–10 | **S3 Quét lái** | 3 khu, mỗi session 1 mức ga (chậm/TB/nhanh) | tách lái khỏi tốc độ |
| 11–14 | **S4 Phối hợp** | 4 khu, đổi hướng nắng | trộn ngược tốc-cua để decorrelate |
| 15–18 | **S5 Tự do/goal** | đi xuyên nhiều khu, tới landmark dừng | tạo goal-states; đổi sáng/chiều |
| (19–20) | bù vùng thiếu | xem histogram sau khi sync | lấp mức ga còn ít |

→ Trộn buổi sáng/chiều. Sau ~12–14 buổi, **dừng lại sync + vẽ histogram** (dưới) rồi quyết có cần buổi bù không.

## ✅ Tiêu chí DỪNG (theo phân bố, không đếm buổi)

Ghép data cũ + mới, kiểm:
1. **Throttle:** không mức ga nào (trong các frame đang-chạy) chiếm **> ~40%**; tầm `[0.06, 0.15]` được phủ
   liên tục (không đóng cục ở 0.075 như cũ); có **~10–15% frame ga=0**.
2. **Có cả pha tăng tốc và giảm tốc/coast** (không chỉ ga đứng yên một mức).
3. **Cảnh:** ít nhất 3–4 nền/khu khác nhau xuất hiện rõ.
4. (kiểm gián tiếp) train lại nhanh → `eff_rank` tăng so với ~8, và `rollout1_ratio` giảm thêm.

## 🚫 Tránh

- ❌ Luôn ghép **một tốc độ với một kiểu maneuver** (vd full ga chỉ khi thẳng) → model lẫn lái với tốc độ.
- ❌ Đường thẳng full-ga dài lê thê (ít transition).
- ❌ Ở lì **vùng chết 1–5%** (stall, nóng motor/ESC).
- ❌ Xe **bò/creep quá chậm hoặc đứng im mà vẫn REC** (frame trùng → hỏng học dynamics).
- ❌ Frame nhòe, cháy nắng, xe tì vật cản đứng im, lái giật làm hỏng sync.
- ❌ **Đổi trim/EPA/dual rate giữa chừng.**

## 🔧 Sau khi thu (pipeline đã sẵn)

```bash
# 1. Lấy data về data/raw/ (auto-upload Tailscale / adb / rclone từ Drive)
# 2. Sync (re-pair frame↔action, khử δ_cam):
python scripts/sync_dataset.py                 # -> actions_synced.csv + imu_synced.csv mỗi session
# 3. Kiểm tra nhanh từng buổi:
python robot/tools/make_video.py --all         # video overlay -> data/videos/
# 4. Backup:
rclone copy data/raw gdrive:JEPA/raw -P
# 5. Re-encode + train lại (latents V-JEPA cache theo từng frame nên chỉ encode buổi MỚI):
python scripts/encode_dataset.py               # bỏ qua session đã có .pt
python scripts/train.py --config configs/train/vjepa_ac.yaml configs/model/vjepa_ac.yaml
# (LeWM:)
python scripts/train_lewm.py --config configs/train/lewm.yaml configs/model/leworldmodel.yaml --set data.frame_skip=5
```

- **Chuẩn hóa action per-dim theo biên THỰC đo từ data** (đừng hardcode ±0.15) — steering & throttle tách
  riêng để tín hiệu throttle nhỏ không bị steering át. (vjepa_ac đang z-score latent; action thì pass thẳng —
  cân nhắc scale throttle lên cho cân với steering nếu cần.)
- Để **đo coverage**, dùng phần "DATA COVERAGE REPORT" trong `scripts/eval_lewm.py` (in histogram steering/
  throttle + % tiến/lùi/dừng) — chạy lại sau khi sync để kiểm tiêu chí dừng ở trên.
