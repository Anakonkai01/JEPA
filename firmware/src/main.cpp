// ============================================================
//  RC Car controller — FlySky i-BUS + WiFi/UDP hub
//  ESP32-S3 WROOM N16R8
//
//  3 chế độ (chọn bằng switch 3 nấc trên CH9):
//    RECORD  (CH9 < 1300)  : lái bằng stick FlySky → servo+ESC,
//                            đồng thời gửi telemetry action về PC @50Hz
//    NEUTRAL (1300–1700)   : kill switch — servo center, ESC neutral
//    AUTO    (CH9 > 1700)  : nhận action 2-byte từ PC qua UDP → servo+ESC
//
//  ESC ở Running Mode 3 (direct reverse) → throttle map TUYẾN TÍNH:
//    esc_us = 1000 + (throttle+1)/2 * 1000   (0=lùi hết, neutral=1500, max=2000)
//
//  i-BUS: FS-iA10B Servo i-BUS → GPIO18 (Serial1 RX), 115200 8N1, KHÔNG đảo.
// ============================================================
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// ============================================================
//  WiFi
// ============================================================
#define WIFI_SSID "Hoang Kim"
#define WIFI_PASS "0984711873"

static const IPAddress STATIC_IP(192, 168, 1, 23);
static const IPAddress GATEWAY  (192, 168, 1,  1);
static const IPAddress SUBNET   (255, 255, 255, 0);
static const uint16_t  UDP_PORT     = 4210;
static const uint32_t  UDP_WATCHDOG_MS = 500;   // AUTO: mất gói PC → neutral

// ============================================================
//  PIN & PWM
// ============================================================
const int SERVO_PIN   = 5;
const int ESC_PIN     = 6;
const int IBUS_RX_PIN = 18;          // Serial1 RX ← i-BUS từ RX FlySky
const int EXT_LED_PIN = 21;          // LED ngoài cho calibrate trễ (nối qua trở 220Ω → GND)
const int PWM_FREQ    = 50;
const int PWM_RES     = 14;          // 14-bit @ 50Hz

// ============================================================
//  GIỚI HẠN (calibrate, xem specs.md)
// ============================================================
const int SERVO_MIN     = 1150;      // full left  (chốt an toàn, trong giới hạn calibrate 1142)
const int SERVO_CENTER  = 1500;      // = trung điểm (1150+1850)/2 → cần giữa ra đúng 1500
const int SERVO_MAX     = 1850;      // full right (chốt an toàn, trong giới hạn calibrate 1880)
const int ESC_MIN       = 1000;      // full reverse (Mode 3)
const int ESC_NEUTRAL   = 1500;
const int ESC_MAX       = 2000;      // full forward

// ============================================================
//  i-BUS
//    Frame 32 byte: 0x20 0x40 | 14 kênh ×2 byte (LE) | checksum ×2
//    Gửi mỗi ~7ms. Giá trị kênh ~1000–2000.
// ============================================================
const uint32_t IBUS_TIMEOUT_MS = 100;   // mất frame → coi như mất sóng RC
const int      CH_STEER  = 0;           // CH1  (index 0)
const int      CH_THROT  = 1;           // CH2  (index 1)
const int      CH_MODE   = 8;           // CH9  (index 8) — switch 3 nấc (mode)
const int      CH_RECORD = 9;           // CH10 (index 9) — switch 2 nấc (record on/off)

uint16_t ibusCh[14]      = {0};
uint32_t ibusLastFrameMs = 0;

// ============================================================
//  MODE
// ============================================================
enum Mode { M_NEUTRAL = 0, M_RECORD = 1, M_AUTO = 2 };
Mode currentMode = M_NEUTRAL;

// ============================================================
//  TELEMETRY (ESP32 → PC) — packed, little-endian (x86 & Xtensa LE khớp)
// ============================================================
struct __attribute__((packed)) Telemetry {
    uint8_t  magic;        // 0xAC
    uint8_t  mode;         // 0=neutral 1=record 2=auto
    uint32_t seq;
    uint32_t esp_ms;
    float    steering;     // [-1, 1]
    float    throttle;     // [-1, 1]
    uint16_t ch_steer_us;  // raw i-BUS µs (debug)
    uint16_t ch_throt_us;
    uint16_t ch_record_us; // CH10 raw µs (record switch)
    uint8_t  rec;          // 1 = đang armed ghi (CH10 > 1500)
};

WiFiUDP    udp;
IPAddress  telemetryDest;            // PC IP — tự phát hiện từ gói PC gửi tới
uint16_t   telemetryPort = 0;
bool       haveDest      = false;
uint32_t   telemSeq      = 0;
uint32_t   lastTelemMs   = 0;
const uint32_t TELEM_INTERVAL_MS = 20;   // 50 Hz

// AUTO control state
uint8_t  autoSteerB    = 127;
uint8_t  autoThrotB    = 127;
uint32_t lastUdpCtrlMs = 0;
bool     udpCtrlActive = false;

// Action hiện tại (để telemetry & debug)
float curSteerNorm = 0.0f;
float curThrotNorm = 0.0f;

// ============================================================
//  PWM HELPERS
// ============================================================
uint32_t usToDuty(int us) {
    return (uint32_t)((us * 16384UL) / 20000);   // period 20000µs, 2^14
}

void setServo(int us) {
    us = constrain(us, SERVO_MIN, SERVO_MAX);
    ledcWrite(SERVO_PIN, usToDuty(us));
}

void setESC(int us) {
    us = constrain(us, ESC_MIN, ESC_MAX);
    ledcWrite(ESC_PIN, usToDuty(us));
}

// steering[-1,1] → servo µs ; throttle[-1,1] → esc µs (Mode 3 tuyến tính)
void driveNorm(float steer, float throt) {
    steer = constrain(steer, -1.0f, 1.0f);
    throt = constrain(throt, -1.0f, 1.0f);
    setServo((int)(SERVO_MIN + (steer + 1.0f) * 0.5f * (SERVO_MAX - SERVO_MIN)));
    setESC  ((int)(ESC_MIN   + (throt + 1.0f) * 0.5f * (ESC_MAX   - ESC_MIN)));
    curSteerNorm = steer;
    curThrotNorm = throt;
}

void driveNeutral() {
    setServo(SERVO_CENTER);
    setESC(ESC_NEUTRAL);
    curSteerNorm = 0.0f;
    curThrotNorm = 0.0f;
}

// RC µs [1000..2000] → normalized [-1..1] quanh tâm 1500
float rcNorm(uint16_t us) {
    float n = ((int)us - 1500) / 500.0f;
    return constrain(n, -1.0f, 1.0f);
}

// ============================================================
//  i-BUS PARSER (byte-by-byte, non-blocking)
// ============================================================
void readIBus() {
    static uint8_t buf[32];
    static int     idx = 0;

    while (Serial1.available()) {
        uint8_t b = Serial1.read();
        if (idx == 0)      { if (b != 0x20) continue; buf[0] = b; idx = 1; }
        else if (idx == 1) { if (b != 0x40) { idx = 0; continue; } buf[1] = b; idx = 2; }
        else {
            buf[idx++] = b;
            if (idx == 32) {
                idx = 0;
                uint16_t chk = 0xFFFF;
                for (int i = 0; i < 30; i++) chk -= buf[i];
                uint16_t rxchk = buf[30] | (buf[31] << 8);
                if (chk == rxchk) {
                    for (int i = 0; i < 14; i++)
                        ibusCh[i] = buf[2 + i * 2] | (buf[3 + i * 2] << 8);
                    ibusLastFrameMs = millis();
                }
            }
        }
    }
}

bool ibusAlive() {
    return (millis() - ibusLastFrameMs) < IBUS_TIMEOUT_MS;
}

// ============================================================
//  UDP RX (từ PC)
//    size 2  : AUTO control [steer_b, throttle_b]
//    size 1  : 0x01=LED on  0x00=LED off  0x02=heartbeat(subscribe)
//    Bất kỳ gói nào cũng cập nhật telemetryDest (auto-discover IP của PC).
// ============================================================
void recvUDP() {
    int pkt = udp.parsePacket();
    if (pkt <= 0) return;

    uint8_t buf[8] = {0};
    int n = udp.read(buf, min(pkt, (int)sizeof(buf)));

    telemetryDest = udp.remoteIP();
    telemetryPort = udp.remotePort();
    haveDest      = true;

    if (n >= 2) {
        autoSteerB    = buf[0];
        autoThrotB    = buf[1];
        lastUdpCtrlMs = millis();
        udpCtrlActive = true;
    } else if (n == 1) {
        if (buf[0] == 0x01) {        // latency LED on (cả onboard lẫn LED ngoài)
            rgbLedWrite(RGB_BUILTIN, 255, 255, 255);
            digitalWrite(EXT_LED_PIN, HIGH);
        } else if (buf[0] == 0x00) { // off
            rgbLedWrite(RGB_BUILTIN, 0, 0, 0);
            digitalWrite(EXT_LED_PIN, LOW);
        }
        // 0x02 = heartbeat: chỉ cần đăng ký dest (đã làm ở trên)
    }
}

// ============================================================
//  TELEMETRY TX (→ PC) @50Hz
// ============================================================
void sendTelemetry() {
    if (!haveDest) return;
    if (millis() - lastTelemMs < TELEM_INTERVAL_MS) return;
    lastTelemMs = millis();

    Telemetry t;
    t.magic       = 0xAC;
    t.mode        = (uint8_t)currentMode;
    t.seq         = telemSeq++;
    t.esp_ms      = millis();
    t.steering    = curSteerNorm;
    t.throttle    = curThrotNorm;
    t.ch_steer_us  = ibusCh[CH_STEER];
    t.ch_throt_us  = ibusCh[CH_THROT];
    t.ch_record_us = ibusCh[CH_RECORD];
    t.rec          = (ibusCh[CH_RECORD] > 1500) ? 1 : 0;

    udp.beginPacket(telemetryDest, telemetryPort);
    udp.write((uint8_t*)&t, sizeof(t));
    udp.endPacket();
}

// ============================================================
//  MODE LOGIC
// ============================================================
Mode computeMode() {
    if (!ibusAlive()) return M_NEUTRAL;          // mất sóng RC → an toàn
    uint16_t sw = ibusCh[CH_MODE];
    if (sw < 1300)      return M_RECORD;
    else if (sw > 1700) return M_AUTO;
    else                return M_NEUTRAL;
}

// ============================================================
//  WiFi
// ============================================================
void setupWiFi() {
    Serial.printf("[WiFi] Kết nối \"%s\"...", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.config(STATIC_IP, GATEWAY, SUBNET);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500); Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] OK — IP %s\n", WiFi.localIP().toString().c_str());
        udp.begin(UDP_PORT);
        Serial.printf("[UDP]  Lắng nghe port %d\n", UDP_PORT);
    } else {
        Serial.println("\n[WiFi] THẤT BẠI — vẫn chạy được RECORD/NEUTRAL qua i-BUS\n");
    }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);

    // PWM — phát neutral ngay để ARM ESC
    ledcAttach(ESC_PIN,   PWM_FREQ, PWM_RES);
    ledcAttach(SERVO_PIN, PWM_FREQ, PWM_RES);
    setESC(ESC_NEUTRAL);
    setServo(SERVO_CENTER);

    // i-BUS UART (RX-only)
    Serial1.begin(115200, SERIAL_8N1, IBUS_RX_PIN, -1);

    pinMode(EXT_LED_PIN, OUTPUT);
    digitalWrite(EXT_LED_PIN, LOW);
    rgbLedWrite(RGB_BUILTIN, 0, 0, 0);

    Serial.println("\n[ESC] Phát neutral để ARM... bật nguồn ESC ngay bây giờ!");
    for (int i = 3; i > 0; i--) { Serial.printf("      ... %d ...\n", i); delay(1000); }
    Serial.println("[ESC] Arm xong!\n");

    setupWiFi();

    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    Serial.println("  FlySky i-BUS hub");
    Serial.println("  CH1=lái  CH2=ga  CH9=mode(RECORD/NEUTRAL/AUTO)");
    Serial.println("  i-BUS @GPIO18 115200  | UDP 4210  | telem 50Hz");
    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
    readIBus();
    recvUDP();

    currentMode = computeMode();

    switch (currentMode) {
        case M_RECORD:
            driveNorm(rcNorm(ibusCh[CH_STEER]), rcNorm(ibusCh[CH_THROT]));
            break;

        case M_AUTO:
            if (udpCtrlActive && (millis() - lastUdpCtrlMs > UDP_WATCHDOG_MS)) {
                driveNeutral();                       // watchdog: mất gói PC
            } else {
                driveNorm(autoSteerB / 255.0f * 2.0f - 1.0f,
                          autoThrotB / 255.0f * 2.0f - 1.0f);
            }
            break;

        case M_NEUTRAL:
        default:
            driveNeutral();
            break;
    }

    sendTelemetry();

    // Debug ra USB Serial @5Hz — verify đọc stick trước khi cắm PC
    static uint32_t dbgMs = 0;
    if (millis() - dbgMs > 200) {
        dbgMs = millis();
        Serial.printf("[%s] CH1:%4u CH2:%4u CH9:%4u CH10:%4u | steer:%+.2f throt:%+.2f | REC:%d iBUS:%s\n",
            currentMode == M_RECORD ? "REC " : currentMode == M_AUTO ? "AUTO" : "NEUT",
            ibusCh[CH_STEER], ibusCh[CH_THROT], ibusCh[CH_MODE], ibusCh[CH_RECORD],
            curSteerNorm, curThrotNorm,
            (ibusCh[CH_RECORD] > 1500) ? 1 : 0, ibusAlive() ? "OK" : "LOST");
    }
}
