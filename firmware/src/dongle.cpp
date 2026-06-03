// ============================================================
//  ESP-NOW ↔ USB serial bridge (DONGLE)
//  ESP32-S3 WROOM N16R8 cắm USB vào PC.
//
//  Vai trò: cầu nối giữa xe (ESP-NOW) và PC (USB CDC serial).
//    • Xe → PC : nhận telemetry 25 byte qua ESP-NOW → in HEX + '\n' ra USB.
//    • PC → xe : đọc 1 dòng HEX từ USB → giải mã byte → esp_now_send về xe.
//
//  Khung tin = hex + '\n' (tự resync, không cần COBS). Dòng hỏng → bỏ qua.
//  MAC peer (CAR_MAC) + channel trong include/peers.h. Build: env:dongle.
// ============================================================
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "peers.h"

// Gói ESP-NOW nhận từ xe (đẩy qua queue ra loop để in serial an toàn).
typedef struct {
    uint8_t len;
    uint8_t data[64];
} EspNowMsg;

static QueueHandle_t rxQueue = nullptr;
static const char HEXC[] = "0123456789abcdef";

// ── ESP-NOW recv (từ xe) — chạy trong WiFi task → chỉ enqueue, không block ──
//   Gắn thêm 1 byte RSSI (int8, dBm — dongle đo sóng từ xe) vào CUỐI payload.
//   PC nhận 25 byte telemetry + 1 byte RSSI = 26 byte/frame.
void onCarRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
    EspNowMsg m;
    int n = (len > (int)sizeof(m.data) - 1) ? (int)sizeof(m.data) - 1 : len;
    memcpy(m.data, data, n);
    m.data[n] = (uint8_t)(info->rx_ctrl ? info->rx_ctrl->rssi : 0);   // RSSI cuối gói
    m.len = (uint8_t)(n + 1);
    xQueueSend(rxQueue, &m, 0);            // timeout 0: queue đầy thì bỏ gói (telemetry tới liên tục)
}

// ── HEX helper ──
static int hexVal(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

void setupEspNow() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    Serial.printf("[ESP-NOW] MAC con nay: %s\n", WiFi.macAddress().c_str());

    esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

    if (esp_now_init() != ESP_OK) {
        Serial.println("[ESP-NOW] init THAT BAI!");
        return;
    }
    esp_now_register_recv_cb(onCarRecv);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, CAR_MAC, 6);
    peer.channel = ESPNOW_CHANNEL;
    peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("[ESP-NOW] add peer THAT BAI (kiem tra CAR_MAC trong peers.h)!");
        return;
    }
    Serial.printf("[ESP-NOW] OK — peer xe %02X:%02X:%02X:%02X:%02X:%02X, ch%d\n",
        CAR_MAC[0], CAR_MAC[1], CAR_MAC[2],
        CAR_MAC[3], CAR_MAC[4], CAR_MAC[5], ESPNOW_CHANNEL);
}

void setup() {
    Serial.begin(115200);
    delay(300);

    rxQueue = xQueueCreate(16, sizeof(EspNowMsg));

    setupEspNow();
    Serial.println("[DONGLE] San sang — cau ESP-NOW <-> USB serial (hex+\\n)");
}

void loop() {
    // (a) Xe → PC : drain queue → in hex + '\n'
    EspNowMsg m;
    while (xQueueReceive(rxQueue, &m, 0) == pdTRUE) {
        char out[2 * sizeof(m.data) + 1];
        int p = 0;
        for (int i = 0; i < m.len; i++) {
            out[p++] = HEXC[m.data[i] >> 4];
            out[p++] = HEXC[m.data[i] & 0x0F];
        }
        out[p++] = '\n';
        Serial.write((const uint8_t*)out, p);
    }

    // (b) PC → xe : gom byte tới '\n' → giải hex → esp_now_send
    static char lineBuf[160];
    static int  lp = 0;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (lp > 0 && (lp % 2) == 0) {
                uint8_t cmd[80];
                int n = 0;
                bool ok = true;
                for (int i = 0; i < lp; i += 2) {
                    int hi = hexVal(lineBuf[i]), lo = hexVal(lineBuf[i + 1]);
                    if (hi < 0 || lo < 0) { ok = false; break; }
                    cmd[n++] = (uint8_t)((hi << 4) | lo);
                }
                if (ok && n > 0) esp_now_send(CAR_MAC, cmd, n);
            }
            lp = 0;                          // reset bất kể hợp lệ hay không (resync)
        } else if (lp < (int)sizeof(lineBuf)) {
            lineBuf[lp++] = c;
        } else {
            lp = 0;                          // tràn dòng → bỏ, resync ở '\n' kế
        }
    }
}
