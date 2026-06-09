package com.jepa.recorder

import android.content.Context
import android.location.Location
import java.io.BufferedWriter
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Ghi 1 session ra bộ nhớ app: frames/NNNNNN.jpg + actions.csv + telemetry.csv + meta.json.
 * Schema KHỚP recorder.py để dùng chung tool offline (sync.py, offline_encode.py).
 * Đường lưu: getExternalFilesDir(null)/sessions/session_<ts>/  → kéo về PC bằng `adb pull`.
 */
class SessionWriter(private val ctx: Context) {

    var dir: File? = null; private set
    var count = 0; private set
    private var actions: BufferedWriter? = null
    private var telem: BufferedWriter? = null
    private var accelW: BufferedWriter? = null
    private var gyroW: BufferedWriter? = null
    private var rotW: BufferedWriter? = null
    private var gpsW: BufferedWriter? = null
    private val lock = Any()

    val active: Boolean get() = dir != null

    fun start() = synchronized(lock) {
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val root = File(ctx.getExternalFilesDir(null), "sessions/session_$ts")
        File(root, "frames").mkdirs()
        actions = File(root, "actions.csv").bufferedWriter().apply {
            // dcam_ms = độ trễ camera đo được từng frame (callback − phơi sáng sensor); t_ms ĐÃ trừ dcam.
            write("frame_idx,t_ms,steering,throttle,seq,esp_ms,mode,dcam_ms\n")
        }
        telem = File(root, "telemetry.csv").bufferedWriter().apply {
            write("t_ms,seq,esp_ms,steering,throttle,mode\n")
        }
        accelW = File(root, "accel.csv").bufferedWriter().apply { write("t_ms,ax,ay,az\n") }
        gyroW  = File(root, "gyro.csv").bufferedWriter().apply { write("t_ms,gx,gy,gz\n") }
        rotW   = File(root, "rotvec.csv").bufferedWriter().apply { write("t_ms,rx,ry,rz\n") }
        gpsW   = File(root, "gps.csv").bufferedWriter().apply { write("t_ms,lat,lon,alt,speed,bearing,acc\n") }
        File(root, "meta.json").writeText(
            """{"started":"$ts","source":"android_camera","save_hz":10}"""
        )
        count = 0
        dir = root
    }

    /** Lưu 1 frame đã encode JPEG + dòng action ghép sẵn. tMs = mốc PHƠI SÁNG sensor (đã trừ δ_cam),
     *  cùng đồng hồ elapsedRealtime với telemetry. dcamMs = độ trễ camera đo được của frame này. */
    fun saveFrame(jpeg: ByteArray, tMs: Long, dcamMs: Double, t: Telemetry?) = synchronized(lock) {
        val d = dir ?: return@synchronized
        count++
        File(d, "frames/%06d.jpg".format(count)).writeBytes(jpeg)
        val steer = t?.steer ?: 0f
        val throt = t?.throt ?: 0f
        val seq = t?.seq ?: -1L
        val esp = t?.espMs ?: -1L
        val mode = t?.mode ?: -1
        // Locale.US BẮT BUỘC: locale VN format dấu phẩy thập phân → vỡ CSV (0,0020).
        actions?.write("$count,$tMs,${"%.4f".format(Locale.US, steer)},${"%.4f".format(Locale.US, throt)}," +
            "$seq,$esp,$mode,${"%.1f".format(Locale.US, dcamMs)}\n")
        // Flush định kỳ (~3s @10Hz): nếu app bị OS kill / rút USB / hết pin giữa buổi thì chỉ mất
        // vài dòng cuối thay vì TOÀN BỘ CSV (frame ghi ngay, nhưng CSV buffer mất hết khi crash).
        if (count % 30 == 0) flushAll()
    }

    /** Đẩy mọi buffer CSV xuống đĩa (không đóng) — gọi định kỳ để chống mất data khi crash. */
    private fun flushAll() {
        try { actions?.flush() } catch (_: Exception) {}
        try { telem?.flush() } catch (_: Exception) {}
        try { accelW?.flush() } catch (_: Exception) {}
        try { gyroW?.flush() } catch (_: Exception) {}
        try { rotW?.flush() } catch (_: Exception) {}
        try { gpsW?.flush() } catch (_: Exception) {}
    }

    /** Stream telemetry 50Hz thô (để re-align offline). */
    fun logTelem(t: Telemetry) = synchronized(lock) {
        telem?.write("${t.tNanos / 1_000_000},${t.seq},${t.espMs}," +
            "${"%.4f".format(Locale.US, t.steer)},${"%.4f".format(Locale.US, t.throt)},${t.mode}\n")
    }

    // Cảm biến điện thoại — Locale.US bắt buộc (dấu chấm). tMs = elapsedRealtime, cùng đồng hồ frame.
    private fun f(v: Float) = "%.5f".format(Locale.US, v)

    fun logAccel(tMs: Long, v: FloatArray) = synchronized(lock) {
        accelW?.write("$tMs,${f(v[0])},${f(v[1])},${f(v[2])}\n")
    }
    fun logGyro(tMs: Long, v: FloatArray) = synchronized(lock) {
        gyroW?.write("$tMs,${f(v[0])},${f(v[1])},${f(v[2])}\n")
    }
    fun logRot(tMs: Long, v: FloatArray) = synchronized(lock) {
        rotW?.write("$tMs,${f(v[0])},${f(v[1])},${f(v[2])}\n")
    }
    fun logGps(tMs: Long, loc: Location) = synchronized(lock) {
        gpsW?.write("$tMs,${"%.7f".format(Locale.US, loc.latitude)},${"%.7f".format(Locale.US, loc.longitude)}," +
            "${"%.2f".format(Locale.US, loc.altitude)},${f(loc.speed)},${f(loc.bearing)},${f(loc.accuracy)}\n")
    }

    fun stop(): String = synchronized(lock) {
        val n = count
        try { actions?.flush(); actions?.close() } catch (_: Exception) {}
        try { telem?.flush(); telem?.close() } catch (_: Exception) {}
        try { accelW?.flush(); accelW?.close() } catch (_: Exception) {}
        try { gyroW?.flush(); gyroW?.close() } catch (_: Exception) {}
        try { rotW?.flush(); rotW?.close() } catch (_: Exception) {}
        try { gpsW?.flush(); gpsW?.close() } catch (_: Exception) {}
        actions = null; telem = null; accelW = null; gyroW = null; rotW = null; gpsW = null
        val path = dir?.name ?: "?"
        dir = null
        "$n frames → $path"
    }
}
