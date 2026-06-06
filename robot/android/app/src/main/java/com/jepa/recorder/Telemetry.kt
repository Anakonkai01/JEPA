package com.jepa.recorder

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Telemetry từ ESP32 — KHỚP 1-1 với recorder.py:
 *   TELEM_FMT = "<BBIIffHHHB"  (25 byte, little-endian), magic = 0xAC
 *   [magic, mode, seq(u32), esp_ms(u32), steer(f32), throt(f32), ch1(u16), ch2(u16), ch3(u16), rec]
 *   byte 26 (nếu có) = RSSI ESP-NOW int8 dBm.
 * Trên dây serial mỗi dòng = HEX + '\n' (dongle/car xuất ra) → bytes.fromhex.
 */
data class Telemetry(
    val tNanos: Long,      // SystemClock.elapsedRealtimeNanos() lúc nhận (đồng hồ chung với frame)
    val mode: Int,
    val seq: Long,
    val espMs: Long,
    val steer: Float,
    val throt: Float,
    val ch1: Int,
    val ch2: Int,
    val ch3: Int,
    val rec: Int,
    val rssi: Int?,
) {
    companion object {
        const val MAGIC = 0xAC
        const val SIZE = 25

        /** Giải 1 dòng hex → Telemetry, null nếu không hợp lệ (dòng debug/hỏng). */
        fun parseHexLine(line: String, tNanos: Long): Telemetry? {
            val s = line.trim()
            if (s.length < SIZE * 2 || s.length % 2 != 0) return null
            val data = try { hexToBytes(s) } catch (e: Exception) { return null }
            if (data.size < SIZE) return null
            if ((data[0].toInt() and 0xFF) != MAGIC) return null
            val bb = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            val magic = bb.get().toInt() and 0xFF
            val mode = bb.get().toInt() and 0xFF
            val seq = bb.int.toLong() and 0xFFFFFFFFL
            val espMs = bb.int.toLong() and 0xFFFFFFFFL
            val steer = bb.float
            val throt = bb.float
            val ch1 = bb.short.toInt() and 0xFFFF
            val ch2 = bb.short.toInt() and 0xFFFF
            val ch3 = bb.short.toInt() and 0xFFFF
            val rec = bb.get().toInt() and 0xFF
            val rssi = if (data.size > SIZE) data[SIZE].toInt() else null   // int8 signed
            return Telemetry(tNanos, mode, seq, espMs, steer, throt, ch1, ch2, ch3, rec, rssi)
        }

        private fun hexToBytes(s: String): ByteArray {
            val out = ByteArray(s.length / 2)
            for (i in out.indices) {
                out[i] = ((Character.digit(s[i * 2], 16) shl 4) or
                          Character.digit(s[i * 2 + 1], 16)).toByte()
            }
            return out
        }

        /** bytes → hex + '\n' để GỬI control xuống ESP32 (giống recorder.send). */
        fun toHexLine(data: ByteArray): ByteArray {
            val sb = StringBuilder(data.size * 2 + 1)
            for (b in data) sb.append("%02x".format(b.toInt() and 0xFF))
            sb.append('\n')
            return sb.toString().toByteArray(Charsets.US_ASCII)
        }
    }
}
