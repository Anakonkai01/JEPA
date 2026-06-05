# JEPA Recorder (Android) — onboard data collection

Thay OpenIPC cam + WFB 5.8G bằng **camera điện thoại đặt trên xe**. App bắt frame (CameraX,
ultrawide) + đọc telemetry ESP32 qua **USB (no-root, usb-serial-for-android)**, lưu cục bộ.
Frame timestamp = **mốc phơi sáng sensor** (app trừ độ trễ camera, cùng đồng hồ telemetry) → ghép chính
xác. Camera có **δ_cam ≈ 100ms** (đo được trên A42), app ghi `dcam_ms` mỗi frame + `src/sync.py` bù —
hết bài toán LED/WFB của rig cũ. Target máy: Samsung Galaxy A42 5G, Android 13.

## Kiến trúc

```
[camera ultrawide] → CameraX ImageAnalysis(RGBA) → JPEG 640px @10Hz ─┐
                                                                      ├→ SessionWriter (frames/ + actions.csv)
[ESP32-S3 xe] → USB CDC native → SerialLink → Telemetry 50Hz ─────────┘   + telemetry.csv (raw, để sync.py)
```
**Điện thoại cắm THẲNG vào ESP32 xe** qua **cổng USB native** ("USB JTAG/serial debug unit", VID
`0x303A`) — C-to-C, **không hub, không dongle**. Phone tự cấp nguồn cho ESP32 qua cổng này. ESP-NOW
chỉ còn là fallback trong firmware.

## Build & cài

1. Mở thư mục `android/` bằng **Android Studio** (Giraffe+). Nó tự tạo Gradle wrapper jar + sync.
   - CLI: cần **Gradle 8.13** (AGP 8.13.2) + JDK 17+. Repo KHÔNG có `gradlew`; dùng gradle cài sẵn:
     `<gradle-8.13>/bin/gradle -p android assembleDebug` (vd `JAVA_HOME=/snap/android-studio/current/jbr`).
2. Cắm A42, bật USB debugging → Run, hoặc `./gradlew installDebug` / `adb install app/build/outputs/apk/debug/app-debug.apk`.
   - Cài đè từ máy khác có thể báo *signature mismatch* → phải gỡ app cũ. **`adb pull` session ra trước**
     (gỡ app XOÁ `Android/data/.../sessions`), rồi `adb uninstall com.jepa.recorder` → cài lại.
3. Mở app → cấp **quyền Camera**. Cắm **cổng native ESP32 → phone** → cấp **quyền USB** (popup).

## Dùng

- Cắm **cổng native ESP32 ("USB JTAG/serial debug unit")** vào phone (xe bật nguồn) → HUD hiện
  `telem OK  mode:… steer/throt`. Không thấy/đèn board không sáng → đang cắm nhầm cổng CH343 ("USB
  Single Serial"); đổi sang cổng native (xem mục "Đã làm" về trở CC).
- Nhấn **● REC** để ghi, **■ STOP** để dừng. HUD đếm frame + fps.
- Kéo data về PC:
  ```bash
  adb pull /sdcard/Android/data/com.jepa.recorder/files/sessions ./data/raw/
  ```
  Mỗi session: `frames/*.jpg`, `actions.csv` (frame_idx,t_ms,steering,throttle,seq,esp_ms,mode,**dcam_ms**),
  `telemetry.csv` (50Hz thô), `accel/gyro/rotvec/gps.csv`, `meta.json`. Chạy `python src/sync.py` →
  **`actions_synced.csv` + `imu_synced.csv`** (đã căn theo thời điểm cảnh thật — DÙNG cái này để train,
  không dùng `actions.csv` gốc).

## Khớp protocol (giống recorder.py)

- Serial 115200, mỗi dòng = **hex + `\n`**. Telemetry 25B `<BBIIffHHHB>` LE, magic `0xAC`, byte 26 = RSSI int8.
- Control gửi ngược: bytes → hex+`\n` (LED `01`/`00`, hoặc `[steer,throt]`). Xem `Telemetry.kt`.

## Đã làm (2026-06-05, đã test A42)

- **Cắm thẳng ESP32 xe** (bỏ dongle + bỏ hub): cắm cổng **NATIVE "USB JTAG/serial debug unit"**
  (VID `0x303A`), **KHÔNG phải** cổng CH343 "USB Single Serial".
  - **Vì sao:** cổng CH343 **thiếu trở CC 5.1k** → phone (host USB-C khó tính) không cấp nguồn qua
    C-to-C trực tiếp (đèn board tắt); cổng native có CC chuẩn → phone bus-power + nhận ngay.
  - Firmware route `Serial` (telemetry/control) ra USB native bằng flag `ARDUINO_USB_MODE=1` +
    `ARDUINO_USB_CDC_ON_BOOT=1` (`firmware/platformio.ini` `[env:car]`). **Nạp code vẫn qua cổng
    CH343** (UART0 download); **chạy/cắm phone qua cổng native.**
  - **Đừng cấp 5V ngoài vào ESP32 khi đang cắm phone** → back-feed VBUS, Samsung khoá cổng. Trên xe:
    để phone bus-power ESP32 + chung GND với BEC (servo/ESC lấy nguồn BEC riêng).
- **Auto-REC theo CH10** (cờ `rec`); nút màn = fallback khi mất telem. RTS=false (RTS giữ ESP32 reset).
- **Khoá shutter nhanh** chống nhòe (Camera2 `CONTROL_AE_TARGET_FPS_RANGE`). Fix locale dấu phẩy CSV.
- **Cảm biến**: `accel/gyro/rotvec/gps.csv` (`SensorLogger.kt`) — cùng đồng hồ frame.
- **Live stream** `PcLink.kt` → `tools/pc_stream_view.py` (port 5055). **Auto-upload nguyên session**
  `Uploader.kt` → `tools/pc_receiver.py` (port 5056) qua Tailscale (`PC_HOST` trong `MainActivity.kt`);
  bù khi PC tắt bằng marker `.uploaded` quét lúc mở app.

## Đã làm (2026-06-06) — app đầy đủ + build/cài verify trên A42

- **Fix δ_cam**: frame `t_ms` giờ = **mốc phơi sáng** (`callback − dcam`, đọc `image.imageInfo.timestamp`,
  A42 `TIMESTAMP_SOURCE=REALTIME`) + thêm cột **`dcam_ms`** (`MainActivity.onFrame` + `SessionWriter`).
  Đo được δ_cam **≈ 100ms** ổn định → data mới hết lệch; data cũ `sync.py` trừ 100ms.
- **Quản lý + xem lại session** (`SessionListActivity`/`SessionPlayerActivity`/`SessionStore`/`SessionAdapter`):
  nút **📁 Sessions** → list (frame/thời lượng/nhãn) + **playback** (overlay steer/throttle) + **xoá /
  đổi nhãn (meta.json) / xem info**.
- **Upload Google Drive** (`DriveUploader.kt`): GoogleSignIn scope `drive.file` + OkHttp **resumable**
  upload (folder "JEPA", marker `.drive_uploaded`, song song với Tailscale). Setup OAuth 1 lần →
  **`android/DRIVE_SETUP.md`** (đã ghi sẵn SHA-1 debug). Nút "Đăng nhập"/"⬆ Drive" trong màn Sessions.
- **🌙 Dim**: phủ đen + hạ độ sáng (AMOLED ≈ tắt pixel), **vẫn ghi** — tiết kiệm pin.
- Deps thêm: `play-services-auth`, `okhttp`, `recyclerview`. **Build = JDK17+ + Gradle 8.13 (AGP 8.13.2)**;
  APK ~7.8MB. Cài lại từ máy khác → signature mismatch (xem mục Build).

## TODO

- **Inference mode** (Phase 4): tái dùng `PcLink` để gửi frame → PC (V-JEPA/CEM) → nhận 2-byte → `serial.send`.
- **Tắt HẲN màn hình** khi quay (foreground service type camera) — Dim hiện chỉ làm tối, chưa tắt hẳn.
- (Tùy chọn) chỉ upload khi có WiFi; tự xoá session `.uploaded`/`.drive_uploaded` cũ; lưu `rotationDegrees`/FOV vào meta.
