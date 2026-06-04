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

## TODO (chưa làm trong MVP)

- **Inference mode**: TCP client gửi frame về PC (RTX chạy V-JEPA/CEM), nhận 2-byte action → `serial.send`.
- **Auto REC theo CH10**: bật/tắt session theo `mode`/`rec` của telemetry (như recorder.py) thay vì nút.
- **Khoá shutter nhanh + exposure** (Camera2 interop) chống motion blur khi xe chạy/rung.
- Xác nhận **VID/PID** dongle nếu USB không nhận (đọc `lsusb`/`dmesg`; sửa `res/xml/usb_device_filter.xml`,
  ESP32-S3 native USB = `0x303A`).
- Lưu `rotationDegrees`/FOV vào meta nếu cần; cân nhắc preview xoay đúng landscape.
