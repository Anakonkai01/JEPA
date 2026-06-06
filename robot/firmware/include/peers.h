#pragma once
// ============================================================
//  Địa chỉ MAC peer cho ESP-NOW (unicast) — DÙNG CHUNG xe & dongle.
//
//  BOOTSTRAP (làm 1 lần): flash lần đầu với placeholder bên dưới,
//  mỗi board in MAC của CHÍNH NÓ ra Serial khi boot:
//      [ESP-NOW] MAC con nay: AA:BB:CC:DD:EE:FF
//  Đọc 2 MAC → điền vào đây → reflash cả 2. Xong là chúng bắt được nhau.
//
//  Xe   gửi telemetry → DONGLE_MAC ; dongle gửi control → CAR_MAC.
//  Channel phải GIỐNG NHAU 2 đầu (không nối router nên tự cố định).
// ============================================================

// MAC con ESP32-S3 trên XE     (board flash env:car — đọc esptool /dev/ttyACM1)
static const uint8_t CAR_MAC[6]    = { 0xE0, 0x72, 0xA1, 0xD5, 0x27, 0xB0 };

// MAC con ESP32-S3 DONGLE      (board flash env:dongle — đọc esptool /dev/ttyACM0)
static const uint8_t DONGLE_MAC[6] = { 0xE0, 0x72, 0xA1, 0xDB, 0xD7, 0x74 };

// Kênh WiFi 2.4GHz cố định cho ESP-NOW (1..13). Phải khớp 2 đầu.
static const uint8_t ESPNOW_CHANNEL = 1;
