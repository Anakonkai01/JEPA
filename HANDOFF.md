# HANDOFF — đọc cái này trước khi tiếp tục

> Bản tóm tắt tình hình cho Claude/người tiếp theo. Cập nhật: **2026-06-05**.
> Tài liệu nền đầy đủ: [CLAUDE.md](CLAUDE.md) · [PLAN.md](PLAN.md) · [android/README.md](android/README.md).
> Cập nhật file này mỗi khi trạng thái đổi.

## Dự án 1 dòng
Action-Conditioned World Model cho xe RC dựa trên **V-JEPA 2.1** (encoder ViT-L đóng băng,
chỉ train AC Predictor ~5M params, CEM planning). Thu data bằng **điện thoại Android đặt trên xe**
(pivot từ camera 5.8GHz WFB đã chết ở ~50m). Deadline **2026-06-15**.

## Trạng thái phase
- **Phase 1 (hạ tầng):** ✅ firmware ESP32 (car+dongle), ESP-NOW LR. Bench OK.
- **Phase 2 (data):** 🟡 app Android onboard BUILT + test trên A42. Đang gỡ nốt khâu cắm USB
  phone↔ESP32 (xem dưới). Chưa có `sync.py` / `offline_encode.py`.
- **Phase 3 (training):** ⏳ chưa bắt đầu (`ac_predictor.py`, `train.py`, baselines).
- **Phase 4 (planning):** ⏳ chưa (`cem_planner.py`, `inference_loop.py`; `controller.py` còn UDP cũ).

## Việc của session vừa rồi (2026-06-05)
**Gỡ vấn đề cắm USB trực tiếp điện thoại ↔ ESP32-S3 xe, và đã FIX + push.**

- **Triệu chứng:** cắm C-to-C cổng **CH343 ("USB Single Serial")** vào phone → board không sáng
  đèn, không nhận. Laptop USB-C / hub UGREEN thì chạy. Cổng **native ("USB JTAG/serial debug
  unit", VID 0x303A)** cắm thẳng phone thì **sáng đèn + nhận**.
- **Nguyên nhân:** cổng CH343 trên board clone **thiếu trở CC 5.1k** → host USB-C khó tính (phone)
  không cấp VBUS. KHÔNG phải board/phone hỏng.
- **Fix (đã làm, build+flash+verify trên laptop):** `firmware/platformio.ini` `[env:car]` thêm
  `-D ARDUINO_USB_MODE=1 -D ARDUINO_USB_CDC_ON_BOOT=1` → `Serial` (telemetry/control) ra **USB
  native**. Telemetry hex `0xAC` đã chạy trên `/dev/ttyACM` cổng native.
- Doc trước ghi NGƯỢC (bảo cắm CH343) → đã sửa: CLAUDE.md, android/README.md, SerialLink.kt comment.
- `MainActivity.kt`: `PC_HOST` → laptop "omarchy" Tailscale **100.84.196.41** (PC cũ 5070ti offline).

### ⚠️ CHƯA VERIFY: cắm firmware mới vào ĐIỆN THOẠI
Mới verify trên laptop. **Việc tiếp theo:**
1. Nạp lại firmware nếu cần: cắm **cổng CH343** → laptop →
   `~/.pio-venv/bin/pio run -d firmware -e car -t upload --upload-port /dev/ttyACM0`
2. Rút ra, cắm **cổng native** thẳng vào phone (C-to-C, **không hub**).
3. Mở app → HUD phải hiện **`telem OK  mode:… steer/throt`**.
4. Lỗi → `adb logcat -s SerialLink` xem app có thấy VID `0x303A` không.

## Quy tắc phần cứng (đừng vi phạm)
- **Cắm phone = cổng NATIVE (303A). Nạp code = cổng CH343 (1a86:55d3).**
- **KHÔNG cấp 5V ngoài vào ESP32 khi đang cắm phone** → back-feed VBUS → Samsung A42 khoá cổng USB
  (phải reboot phone mới hết). Trên xe: **để phone bus-power ESP32** qua cổng native + **chung GND
  với BEC** (servo/ESC lấy nguồn BEC riêng). Cần nguồn ngoài → powered hub / cách ly VBUS.
- Gỡ app (signature mismatch khi build máy khác) **XOÁ** `Android/data/.../sessions` →
  **`adb pull` session ra trước** rồi mới `adb uninstall com.jepa.recorder`.

## Data
- App lưu: `/sdcard/Android/data/com.jepa.recorder/files/sessions/session_<ts>/`
  (`frames/*.jpg`, `actions.csv`, `telemetry.csv` 50Hz, `accel/gyro/rotvec/gps.csv`, `meta.json`).
- **Backup 16 session (2026-06-05): `data/raw/phone_backup_20260605/`** (đã kéo về laptop omarchy).
- Lấy data không cáp: chạy `python tools/pc_receiver.py` (port 5056) → app auto-upload zip sau mỗi
  STOP → giải nén vào `data/raw/`. Xem live: `python tools/pc_stream_view.py` (port 5055).

## Bước tiếp theo gợi ý (sau khi xác nhận telem trên phone)
1. Thu một ít data thật qua app → kiểm `data/raw/` đủ frames+csv.
2. Viết `src/sync.py` (re-align frame↔action theo telemetry.csv) + `src/offline_encode.py`
   (pre-encode latent V-JEPA → `data/latents/*.pt`).
3. Phase 3: `src/ac_predictor.py` + `src/train.py`.

## Lệnh hay dùng
```bash
# Firmware (dùng venv, KHÔNG conda)
~/.pio-venv/bin/pio run -d firmware -e car -t upload --upload-port /dev/ttyACM0
# Cài app
cd android && ./gradlew installDebug
# Nhận data / xem live
python tools/pc_receiver.py        # 5056, auto-upload
python tools/pc_stream_view.py     # 5055, live
# Map cổng USB ↔ chip
for d in /dev/ttyACM*; do udevadm info -q property -n $d | grep -E 'ID_MODEL=|ID_VENDOR_ID'; done
```
