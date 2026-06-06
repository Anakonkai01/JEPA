// ============================================================
//  Servo calibration — JOG mode (cho servo MỚI)
//  Không dính sai số phản xạ: nudge tới khi lốp VỪA chạm khung rồi mark.
//  Build/flash/monitor qua cổng CH343 (UART0) — env riêng, KHÔNG đụng env:car:
//      ~/.pio-venv/bin/pio run -d firmware -e servocal -t upload --upload-port /dev/ttyACM0
//      ~/.pio-venv/bin/pio device monitor -p /dev/ttyACM0 -b 115200
//
//  Gõ phím trong monitor (có/không Enter đều được):
//      a / d  = nudge ∓10µs (trái / phải)
//      A / D  = nudge ∓1µs (mịn — chốt đúng điểm chạm)
//      l      = mark biên TRÁI tại vị trí hiện tại
//      r      = mark biên PHẢI
//      c      = mark TÂM (chỉnh tới khi bánh thẳng rồi mark)
//      s      = về 1500
//      p      = in lại kết quả
//
//  ⚠️ Nudge CHẬM, DỪNG ngay khi lốp vừa chạm khung — ĐỪNG giữ servo tì vào
//     stop (stall → nóng/hư). Nên dò khi NHẤC xe để nhẹ linkage.
// ============================================================
#include <Arduino.h>

const int SERVO_PIN = 5;
const int PWM_FREQ  = 50;
const int PWM_RES   = 14;

// Phải khớp clamp trong main.cpp để biết biên servo mới có "phủ" được không
const int CLAMP_MIN = 1150;
const int CLAMP_MAX = 1850;

static uint32_t usToDuty(int us) { return (uint32_t)((us * 16384UL) / 20000); }

static int us = 1500, mLeft = 0, mRight = 0, mCenter = 0;

static void apply() { ledcWrite(SERVO_PIN, usToDuty(us)); }

static void report() {
    Serial.printf("us=%4d | L=%4d R=%4d C=%4d", us, mLeft, mRight, mCenter);
    if (mLeft && mRight) {
        bool safe = (mLeft < CLAMP_MIN && mRight > CLAMP_MAX);
        Serial.printf("  | clamp [%d,%d] %s", CLAMP_MIN, CLAMP_MAX,
            safe ? "AN TOAN (nam trong bien co khi)"
                 : "!! HEP HON BIEN — phai thu hep clamp");
    }
    if (mCenter)
        Serial.printf("  | tam lech 1500: %+d us", mCenter - 1500);
    Serial.println();
}

void setup() {
    Serial.begin(115200);
    delay(400);
    ledcAttach(SERVO_PIN, PWM_FREQ, PWM_RES);
    apply();
    Serial.println("\n=== SERVO JOG CALIB (servo moi) ===");
    Serial.println("a/d=∓10  A/D=∓1  l/r/c=mark L/R/Center  s=1500  p=print");
    Serial.println("Nudge CHAM, DUNG khi lop vua cham khung. Dung giu vao stop!");
    report();
}

void loop() {
    if (!Serial.available()) return;
    char k = (char)Serial.read();
    switch (k) {
        case 'a': us -= 10; break;
        case 'd': us += 10; break;
        case 'A': us -= 1; break;
        case 'D': us += 1; break;
        case 'l': mLeft   = us; Serial.println(">> mark LEFT");   break;
        case 'r': mRight  = us; Serial.println(">> mark RIGHT");  break;
        case 'c': mCenter = us; Serial.println(">> mark CENTER"); break;
        case 's': us = 1500; break;
        case 'p': report(); return;
        default:  return;            // bỏ qua phím lạ / '\n' / '\r'
    }
    us = constrain(us, 1000, 2000);  // chốt cứng an toàn tuyệt đối khi jog
    apply();
    report();
}
