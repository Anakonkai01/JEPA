# JEPA Recorder (Android) — onboard data collection

Thay OpenIPC cam + WFB 5.8G bằng **camera điện thoại đặt trên xe**. App bắt frame (CameraX,
ultrawide) + đọc telemetry ESP32 qua **USB (no-root, usb-serial-for-android)**, lưu cục bộ.
Frame timestamp = `elapsedRealtime` (cùng đồng hồ telemetry) → **ghép chính xác, hết bài toán
L_cam/LED/WFB**. Target máy: Samsung Galaxy A42 5G, Android 13.

## Kiến trúc

```
[camera ultrawide] → CameraX ImageAnalysis(RGBA) → JPEG 640px @10Hz ─┐
                                                                      ├→ SessionWriter (frames/ + actions.csv)
[ESP32/dongle] → USB CDC → SerialLink → Telemetry 50Hz ──────────────┘   + telemetry.csv (raw, để sync.py)
```
Hub UGREEN (OTG): điện thoại ↔ dongle (USB). Dongle ↔ car qua ESP-NOW <0.3m (đã LR). Không cần
sửa firmware. (Sau này có thể nối thẳng phone↔car ESP32 USB, bỏ dongle.)

## Build & cài

1. Mở thư mục `android/` bằng **Android Studio** (Giraffe+). Nó tự tạo Gradle wrapper jar + sync.
   - CLI: `cd android && gradle wrapper && ./gradlew assembleDebug` (cần Gradle 8.7 cài sẵn).
2. Cắm A42, bật USB debugging → Run, hoặc `./gradlew installDebug` / `adb install app/build/outputs/apk/debug/app-debug.apk`.
3. Mở app → cấp **quyền Camera**. Cắm hub + dongle → cấp **quyền USB** (popup).

## Dùng

- Cắm dongle (xe bật nguồn) → HUD hiện `telem OK  mode:… steer/throt`. Không thấy → kiểm hub/VID.
- Nhấn **● REC** để ghi, **■ STOP** để dừng. HUD đếm frame + fps.
- Kéo data về PC:
  ```bash
  adb pull /sdcard/Android/data/com.jepa.recorder/files/sessions ./data/raw/
  ```
  Mỗi session: `frames/*.jpg`, `actions.csv` (frame_idx,t_ms,steering,throttle,seq,esp_ms,mode),
  `telemetry.csv` (50Hz thô), `meta.json` — **cùng schema recorder.py** → dùng thẳng `sync.py`/`offline_encode.py`.

## Khớp protocol (giống recorder.py)

- Serial 115200, mỗi dòng = **hex + `\n`**. Telemetry 25B `<BBIIffHHHB>` LE, magic `0xAC`, byte 26 = RSSI int8.
- Control gửi ngược: bytes → hex+`\n` (LED `01`/`00`, hoặc `[steer,throt]`). Xem `Telemetry.kt`.

## Đã làm (2026-06-05, đã test A42)

- **Cắm thẳng ESP32 xe** (bỏ dongle): cắm cổng **"USB Single Serial"** (UART bridge), KHÔNG phải cổng
  "USB JTAG/serial debug unit". `firmware/src/main.cpp` phun telemetry hex + đọc control hex trên USB.
- **Auto-REC theo CH10** (cờ `rec`); nút màn = fallback khi mất telem. RTS=false (RTS giữ ESP32 reset).
- **Khoá shutter nhanh** chống nhòe (Camera2 `CONTROL_AE_TARGET_FPS_RANGE`). Fix locale dấu phẩy CSV.
- **Cảm biến**: `accel/gyro/rotvec/gps.csv` (`SensorLogger.kt`) — cùng đồng hồ frame.
- **Live stream** `PcLink.kt` → `tools/pc_stream_view.py` (port 5055). **Auto-upload nguyên session**
  `Uploader.kt` → `tools/pc_receiver.py` (port 5056) qua Tailscale (`PC_HOST` trong `MainActivity.kt`);
  bù khi PC tắt bằng marker `.uploaded` quét lúc mở app.

## TODO

- **Inference mode** (Phase 4): tái dùng `PcLink` để gửi frame → PC (V-JEPA/CEM) → nhận 2-byte → `serial.send`.
- **Tắt hẳn màn hình** khi quay (foreground service type camera) để tiết kiệm pin.
- (Tùy chọn) chỉ upload khi có WiFi; tự xoá session `.uploaded` cũ; lưu `rotationDegrees`/FOV vào meta.
