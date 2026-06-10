package com.jepa.recorder

import android.util.Log
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileInputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue

/**
 * Gửi NGUYÊN session (frames + mọi CSV: actions/telemetry/accel/gyro/rotvec/gps) về PC qua TCP
 * sau khi STOP — KHÔNG cần cắm cáp. Nén zip rồi gửi [u32 name_len][name][u64 zip_len][zip], chờ ack.
 * Chạy được qua Tailscale (5G ngoài trời). Hàng đợi bền: gửi lỗi (mất mạng) → thử lại, không mất data.
 * PC chạy tools/pc_receiver.py để nhận + giải nén vào data/raw/<name>/.
 */
class Uploader(
    private val host: String,
    private val port: Int,
    private val cacheDir: File,
    private val onStatus: (String) -> Unit,
) {
    private val queue = LinkedBlockingQueue<File>()
    @Volatile private var running = false
    private var thread: Thread? = null
    private val TAG = "Uploader"

    fun start() {
        if (running) return
        running = true
        thread = Thread { loop() }.also { it.isDaemon = true; it.start() }
    }

    fun stop() { running = false; thread?.interrupt() }

    fun enqueue(sessionDir: File) {
        queue.offer(sessionDir)
        onStatus("up: chờ gửi ${queue.size}")
    }

    /** Quét các session CHƯA gửi (thiếu marker .uploaded) → xếp hàng. Gọi lúc mở app để bù
     *  những buổi thu khi PC tắt: lần sau mở app + PC bật + cùng Tailscale là tự gửi hết, không cáp. */
    fun enqueuePending(sessionsRoot: File) {
        val dirs = sessionsRoot.listFiles { f -> f.isDirectory && f.name.startsWith("session_") } ?: return
        var k = 0
        for (d in dirs.sortedBy { it.name }) {
            if (!File(d, ".uploaded").exists() && File(d, "actions.csv").exists()) { queue.offer(d); k++ }
        }
        if (k > 0) onStatus("up: tồn $k session chưa gửi")
    }

    private fun loop() {
        while (running) {
            val dir = try { queue.take() } catch (e: InterruptedException) { break }
            val ok = try { send(dir) } catch (e: Exception) { Log.w(TAG, "send fail: ${e.message}"); false }
            if (ok) {
                onStatus("up OK: ${dir.name}")
            } else if (running) {
                queue.offer(dir)                                  // mất mạng → thử lại sau
                onStatus("up: lỗi, thử lại (${queue.size})")
                try { Thread.sleep(5000) } catch (_: InterruptedException) { break }
            }
        }
    }

    private fun send(dir: File): Boolean {
        // .uploaded đã có = session từng gửi OK (bị enqueue trùng enqueue/enqueuePending) → bỏ qua
        if (!dir.exists() || File(dir, ".uploaded").exists()) return true
        val zip = File(cacheDir, "${dir.name}.zip")
        try {
            Zips.zipDir(dir, zip)
            Socket().use { sock ->
                sock.connect(InetSocketAddress(host, port), 4000)
                sock.soTimeout = 20000
                val out = DataOutputStream(BufferedOutputStream(sock.getOutputStream()))
                val name = dir.name.toByteArray(Charsets.UTF_8)
                out.writeInt(name.size); out.write(name)
                out.writeLong(zip.length())
                FileInputStream(zip).use { it.copyTo(out) }
                out.flush()
                val ack = sock.getInputStream().read()             // PC gửi 0x01 khi đã giải nén OK
                if (ack == 1) { File(dir, ".uploaded").createNewFile(); return true }
                return false
            }
        } finally {
            zip.delete()
        }
    }
}
