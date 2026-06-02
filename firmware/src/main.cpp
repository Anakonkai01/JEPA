#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// ============================================================
//  WiFi CONFIG
// ============================================================
#define WIFI_SSID "Hoang Kim"
#define WIFI_PASS "0984711873"

static const IPAddress STATIC_IP(192, 168, 1, 23);
static const IPAddress GATEWAY  (192, 168, 1,  1);
static const IPAddress SUBNET   (255, 255, 255, 0);
static const uint16_t  UDP_PORT    = 4210;
static const uint32_t  WATCHDOG_MS = 500;

// ============================================================
//  PIN & PWM
// ============================================================
const int SERVO_PIN = 5;
const int ESC_PIN   = 6;
const int PWM_FREQ  = 50;
const int PWM_RES   = 14;

// ============================================================
//  SERVO LIMITS  (calibrated, xem specs.md)
// ============================================================
const int SERVO_FULL_LEFT    = 1250;
const int SERVO_SLIGHT_LEFT  = 1340;
const int SERVO_CENTER       = 1500;
const int SERVO_SLIGHT_RIGHT = 1660;
const int SERVO_FULL_RIGHT   = 1750;

// ============================================================
//  ESC SPEED LEVELS
// ============================================================
const int ESC_NEUTRAL   = 1500;
const int ESC_FWD_SLOW  = 1540;
const int ESC_FWD_MED   = 1570;
const int ESC_BRAKE_VAL = 1460;
const int ESC_REV_SLOW  = 1450;
const int ESC_REV_MED   = 1400;

// ============================================================
//  UDP THROTTLE BYTE ZONES
//  < 64       → muốn lùi (kích double-tap sequence)
//  64 – 126   → neutral zone
//  >= 127     → tiến
// ============================================================
static const uint8_t REV_THRESHOLD = 64;

// ============================================================
//  STATE
//  REV_ARM1: đang gửi brake pulse (700ms) để vào brake state ESC
//  REV_ARM2: đang gửi neutral (300ms) trước tap 2
//  REVERSE:  đang lùi thực sự
// ============================================================
enum ESCState { NEUTRAL_ST, FORWARD, BRAKING, REV_ARM1, REV_ARM2, REVERSE };
ESCState escState = NEUTRAL_ST;

int      currentServo     = SERVO_CENTER;
int      currentESC       = ESC_NEUTRAL;
uint32_t revTimerMs       = 0;   // timer cho double-tap sequence
WiFiUDP  udp;
uint32_t lastPacketMs     = 0;
bool     udpControlActive = false;

// ============================================================
//  HELPERS
// ============================================================
uint32_t usToDuty(int us) {
    return (uint32_t)((us * 16384UL) / 20000);
}

void setServo(int us) {
    us = constrain(us, SERVO_FULL_LEFT, SERVO_FULL_RIGHT);
    currentServo = us;
    ledcWrite(SERVO_PIN, usToDuty(us));
}

void setESC(int us) {
    us = constrain(us, 1000, 2000);
    currentESC = us;
    ledcWrite(ESC_PIN, usToDuty(us));
}

// Neutral tức thì — dùng cho UDP watchdog (không có delay).
void stopImmediate() {
    setESC(ESC_NEUTRAL);
    setServo(SERVO_CENTER);
    escState = NEUTRAL_ST;
}

// Phanh + neutral — dùng cho Serial (delay OK).
void stopSerial() {
    if (escState == FORWARD) {
        Serial.println("[DỪNG] Phanh...");
        setESC(ESC_BRAKE_VAL);
        delay(400);
    }
    setESC(ESC_NEUTRAL);
    setServo(SERVO_CENTER);
    escState = NEUTRAL_ST;
    Serial.println("[DỪNG] Neutral + center.");
}

// Double-tap reverse (Serial, có delay OK).
void doReverseSerial(int rev_pulse) {
    if (escState == FORWARD) {
        setESC(ESC_BRAKE_VAL); escState = BRAKING;
        delay(600);
        setESC(ESC_NEUTRAL); delay(300);
    }
    setESC(ESC_BRAKE_VAL); escState = BRAKING;
    delay(700);
    setESC(ESC_NEUTRAL); delay(300);
    setESC(rev_pulse);   escState = REVERSE;
    Serial.printf("[LÙI] Serial: %d us\n", rev_pulse);
}

// ============================================================
//  NON-BLOCKING DOUBLE-TAP STATE MACHINE
//  Gọi mỗi loop() — xử lý timing mà không block.
//
//  QuicRun 8BL150 sequence:
//    Tap 1: ESC_BRAKE_VAL (~700ms) → ESC vào brake mode
//    Pause: ESC_NEUTRAL   (~300ms)
//    Tap 2: ESC_REV_SLOW          → ESC nhận = REVERSE
// ============================================================
void tickReverse() {
    if (escState == REV_ARM1 && millis() - revTimerMs >= 700) {
        setESC(ESC_NEUTRAL);
        escState   = REV_ARM2;
        revTimerMs = millis();
    }
    if (escState == REV_ARM2 && millis() - revTimerMs >= 300) {
        setESC(ESC_REV_SLOW);
        escState = REVERSE;
        Serial.println("[LÙI] UDP: đang lùi");
    }
}

// ============================================================
//  UDP PACKET HANDLER
//
//  byte[0]  steering : 0=full-left  127=center  255=full-right
//  byte[1]  throttle :
//    < 64    → kích double-tap để lùi (non-blocking)
//    64-126  → neutral
//    >= 127  → tiến (1500–2000µs)
// ============================================================
void handleUDP(uint8_t steer_b, uint8_t throttle_b) {
    // Steering áp dụng mọi lúc kể cả khi arming
    int servo_us = 1142 + (int)(steer_b / 255.0f * (1880 - 1142));
    setServo(servo_us);

    // Đang trong arming sequence → không can thiệp ESC
    if (escState == REV_ARM1 || escState == REV_ARM2) {
        lastPacketMs = millis(); udpControlActive = true;
        return;
    }

    if (throttle_b < REV_THRESHOLD) {
        // Muốn lùi
        if (escState == REVERSE) {
            // Đã lùi rồi, giữ nguyên ESC_REV_SLOW
        } else {
            // Bắt đầu double-tap (từ forward hoặc neutral đều như nhau)
            if (escState == FORWARD) {
                // Cần brake ngắn trước tap 1
                setESC(ESC_BRAKE_VAL);
                delay(200);             // brake ngắn để ESC ổn định
                setESC(ESC_NEUTRAL);
                delay(100);
            }
            setESC(ESC_BRAKE_VAL);      // Tap 1 bắt đầu
            escState   = REV_ARM1;
            revTimerMs = millis();
        }
    } else if (throttle_b >= 127) {
        // Tiến
        int esc_us = 1500 + (int)((throttle_b - 127) / 128.0f * 500);
        esc_us     = constrain(esc_us, 1500, 2000);
        escState   = (esc_us > 1505) ? FORWARD : NEUTRAL_ST;
        setESC(esc_us);
    } else {
        // Neutral zone (64–126)
        stopImmediate();
    }

    lastPacketMs     = millis();
    udpControlActive = true;
}

// ============================================================
//  WiFi SETUP
// ============================================================
void setupWiFi() {
    Serial.printf("[WiFi] Kết nối tới \"%s\"...", WIFI_SSID);
    WiFi.config(STATIC_IP, GATEWAY, SUBNET);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500); Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] OK — IP: %s\n", WiFi.localIP().toString().c_str());
        udp.begin(UDP_PORT);
        Serial.printf("[UDP]  Lắng nghe port %d\n\n", UDP_PORT);
    } else {
        Serial.println("\n[WiFi] THẤT BẠI — chỉ chạy Serial mode\n");
    }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);

    ledcAttach(ESC_PIN,   PWM_FREQ, PWM_RES);
    ledcWrite (ESC_PIN,   usToDuty(ESC_NEUTRAL));
    ledcAttach(SERVO_PIN, PWM_FREQ, PWM_RES);
    ledcWrite (SERVO_PIN, usToDuty(SERVO_CENTER));

    Serial.println("\n[ESC] Phát neutral để ARM... bật nguồn ESC ngay bây giờ!");
    for (int i = 4; i > 0; i--) {
        Serial.printf("      ... %d ...\n", i); delay(1000);
    }
    Serial.println("[ESC] Arm xong!\n");

    setupWiFi();

    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    Serial.println("  Serial : w/W tiến  s dừng  a-d lái  r/R lùi");
    Serial.println("  UDP    : byte[1]<64=lùi  64-126=neutral  >=127=tiến");
    Serial.println("  Watchdog: 500ms");
    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
    // 1. Non-blocking reverse arming state machine
    tickReverse();

    // 2. Nhận UDP
    int pktSize = udp.parsePacket();
    if (pktSize >= 2) {
        uint8_t buf[4] = {0};
        udp.read(buf, min(pktSize, (int)sizeof(buf)));
        handleUDP(buf[0], buf[1]);
    }

    // 3. Watchdog (bỏ qua khi đang arming reverse)
    if (udpControlActive &&
        escState != NEUTRAL_ST && escState != REV_ARM1 && escState != REV_ARM2 &&
        (millis() - lastPacketMs > WATCHDOG_MS)) {
        Serial.printf("[WATCHDOG] Timeout %dms → Neutral\n", WATCHDOG_MS);
        stopImmediate();
    }

    // 4. Serial commands
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        while (Serial.available() > 0) Serial.read();

        switch (cmd) {
            case 'w': setESC(ESC_FWD_SLOW); escState = FORWARD;
                      Serial.printf("[TIẾN] %d us\n", ESC_FWD_SLOW); break;
            case 'W': setESC(ESC_FWD_MED);  escState = FORWARD;
                      Serial.printf("[TIẾN] %d us\n", ESC_FWD_MED);  break;
            case 's': case ' ': stopSerial(); break;
            case 'r': doReverseSerial(ESC_REV_SLOW); break;
            case 'R': doReverseSerial(ESC_REV_MED);  break;
            case 'a': setServo(SERVO_FULL_LEFT);    Serial.println("[LÁI] Trái hết");  break;
            case 'z': setServo(SERVO_SLIGHT_LEFT);  Serial.println("[LÁI] Trái nhẹ"); break;
            case 'q': setServo(SERVO_CENTER);       Serial.println("[LÁI] Thẳng");    break;
            case 'c': setServo(SERVO_SLIGHT_RIGHT); Serial.println("[LÁI] Phải nhẹ"); break;
            case 'd': setServo(SERVO_FULL_RIGHT);   Serial.println("[LÁI] Phải hết"); break;
            case 'i': Serial.printf("[STATUS] Servo:%dµs ESC:%dµs WiFi:%s State:%d\n",
                          currentServo, currentESC,
                          WiFi.isConnected() ? WiFi.localIP().toString().c_str() : "OFF",
                          (int)escState); break;
        }
    }
}
