package com.jepa.recorder

import android.content.Context
import java.io.BufferedWriter
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Ghi 1 session ra bộ nhớ app: frames/*.jpg + actions.csv + telemetry.csv + meta.json.
 * Schema KHỚP recorder.py để dùng chung tool offline (sync.py, offline_encode.py).
 * Đường lưu: getExternalFilesDir(null)/sessions/session_<ts>/  → kéo về PC bằng `adb pull`.
 */
class SessionWriter(private val ctx: Context) {

    var dir: File? = null; private set
    var count = 0; private set
    private var actions: BufferedWriter? = null
    private var telem: BufferedWriter? = null
    private val lock = Any()

    val active: Boolean get() = dir != null

    fun start() = synchronized(lock) {
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val root = File(ctx.getExternalFilesDir(null), "sessions/session_$ts")
        File(root, "frames").mkdirs()
        actions = File(root, "actions.csv").bufferedWriter().apply {
            write("frame_idx,t_ms,steering,throttle,seq,esp_ms,mode\n")
        }
        telem = File(root, "telemetry.csv").bufferedWriter().apply {
            write("t_ms,seq,esp_ms,steering,throttle,mode\n")
        }
        File(root, "meta.json").writeText(
            """{"started":"$ts","source":"android_camera","save_hz":10}"""
        )
        count = 0
        dir = root
    }

    /** Lưu 1 frame đã encode JPEG + dòng action ghép sẵn. tMs = elapsedRealtime ms. */
    fun saveFrame(jpeg: ByteArray, tMs: Long, t: Telemetry?) = synchronized(lock) {
        val d = dir ?: return
        count++
        File(d, "frames/%06d.jpg".format(count)).writeBytes(jpeg)
        val steer = t?.steer ?: 0f
        val throt = t?.throt ?: 0f
        val seq = t?.seq ?: -1L
        val esp = t?.espMs ?: -1L
        val mode = t?.mode ?: -1
        actions?.write("$count,$tMs,${"%.4f".format(steer)},${"%.4f".format(throt)},$seq,$esp,$mode\n")
    }

    /** Stream telemetry 50Hz thô (để re-align offline). */
    fun logTelem(t: Telemetry) = synchronized(lock) {
        telem?.write("${t.tNanos / 1_000_000},${t.seq},${t.espMs}," +
            "${"%.4f".format(t.steer)},${"%.4f".format(t.throt)},${t.mode}\n")
    }

    fun stop(): String = synchronized(lock) {
        val n = count
        try { actions?.flush(); actions?.close() } catch (_: Exception) {}
        try { telem?.flush(); telem?.close() } catch (_: Exception) {}
        actions = null; telem = null
        val path = dir?.name ?: "?"
        dir = null
        "$n frames → $path"
    }
}
