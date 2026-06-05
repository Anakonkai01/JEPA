package com.jepa.recorder

import android.content.Context
import org.json.JSONObject
import java.io.File

/** Thông tin tóm tắt 1 session (đọc từ frames/ + actions.csv + meta.json). */
data class SessionInfo(
    val dir: File,
    val name: String,
    val frames: Int,
    val durationSec: Double,
    val steerMean: Float, val steerStd: Float,
    val throtMean: Float, val throtStd: Float,
    val dcamMeanMs: Float,
    val uploaded: Boolean,        // Tailscale (.uploaded)
    val driveUploaded: Boolean,   // Google Drive (.drive_uploaded)
    val label: String,
)

/**
 * Quản lý các session đã ghi trong bộ nhớ app (getExternalFilesDir/sessions). Dùng chung cho
 * SessionListActivity + SessionPlayerActivity. Đổi tên = ghi field `label` vào meta.json (GIỮ tên thư
 * mục — an toàn hơn rename, không phá liên kết .uploaded/đường dẫn).
 */
object SessionStore {

    fun root(ctx: Context): File = File(ctx.getExternalFilesDir(null), "sessions")

    fun list(ctx: Context): List<SessionInfo> {
        val dirs = root(ctx).listFiles { f -> f.isDirectory && f.name.startsWith("session_") }
            ?: return emptyList()
        return dirs.sortedByDescending { it.name }.map { info(it) }   // mới nhất lên đầu
    }

    /** Một lượt đọc actions.csv → thời lượng + mean/std steer-throttle + mean dcam. */
    fun info(dir: File): SessionInfo {
        val frames = File(dir, "frames").listFiles { f -> f.name.endsWith(".jpg") }?.size ?: 0
        var t0 = 0L; var t1 = 0L; var n = 0
        var sSum = 0.0; var sSq = 0.0; var thSum = 0.0; var thSq = 0.0; var dSum = 0.0
        val af = File(dir, "actions.csv")
        if (af.exists()) {
            af.useLines { lines ->
                lines.drop(1).forEach { ln ->
                    val p = ln.split(',')
                    if (p.size >= 4) {
                        val t = p[1].toLongOrNull() ?: return@forEach
                        if (n == 0) t0 = t
                        t1 = t
                        val s = p[2].toFloatOrNull() ?: 0f
                        val th = p[3].toFloatOrNull() ?: 0f
                        sSum += s; sSq += s * s; thSum += th; thSq += th * th
                        if (p.size >= 8) dSum += p[7].toDoubleOrNull() ?: 0.0
                        n++
                    }
                }
            }
        }
        fun std(sum: Double, sq: Double, c: Int): Float =
            if (c > 0) Math.sqrt(Math.max(0.0, sq / c - (sum / c) * (sum / c))).toFloat() else 0f
        return SessionInfo(
            dir = dir, name = dir.name, frames = frames,
            durationSec = if (n > 1) (t1 - t0) / 1000.0 else 0.0,
            steerMean = if (n > 0) (sSum / n).toFloat() else 0f, steerStd = std(sSum, sSq, n),
            throtMean = if (n > 0) (thSum / n).toFloat() else 0f, throtStd = std(thSum, thSq, n),
            dcamMeanMs = if (n > 0) (dSum / n).toFloat() else 0f,
            uploaded = File(dir, ".uploaded").exists(),
            driveUploaded = File(dir, ".drive_uploaded").exists(),
            label = readMeta(dir).optString("label", ""),
        )
    }

    fun readMeta(dir: File): JSONObject =
        try { JSONObject(File(dir, "meta.json").readText()) } catch (e: Exception) { JSONObject() }

    fun setLabel(dir: File, label: String) {
        val m = readMeta(dir).put("label", label)
        try { File(dir, "meta.json").writeText(m.toString()) } catch (_: Exception) {}
    }

    fun delete(dir: File): Boolean = dir.deleteRecursively()
}
