package com.jepa.recorder

import android.util.Log
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Stream best-effort frame (JPEG + meta JSON) về PC qua TCP để XEM TRỰC TIẾP + lưu bản sao.
 * Phone = client, PC = server (tools/pc_stream_view.py). KHÔNG chặn camera: hàng đợi nhỏ,
 * đầy thì bỏ frame (live view chấp nhận rớt). Ghi cục bộ (SessionWriter) vẫn là nguồn CHÍNH.
 *
 * Khung mỗi frame:  [u32 meta_len][meta utf-8][u32 jpeg_len][jpeg]   (big-endian).
 * Tự kết nối lại nếu rớt. Dùng được qua Tailscale: chỉ cần PC_HOST = IP 100.x của PC.
 */
class PcLink(
    private val host: String,
    private val port: Int,
    private val onStatus: (String) -> Unit,
) {
    private class Frame(val jpeg: ByteArray, val meta: String)

    private val queue = ArrayBlockingQueue<Frame>(4)
    private val running = AtomicBoolean(false)
    @Volatile var connected = false; private set
    private var thread: Thread? = null
    private val TAG = "PcLink"

    fun start() {
        if (running.getAndSet(true)) return
        thread = Thread { loop() }.also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        running.set(false)
        thread?.interrupt()
    }

    /** Gọi từ camera thread — không block; đầy queue thì bỏ frame. */
    fun offer(jpeg: ByteArray, meta: String) {
        if (!connected) return
        queue.offer(Frame(jpeg, meta))
    }

    private fun loop() {
        while (running.get()) {
            var sock: Socket? = null
            try {
                sock = Socket()
                sock.connect(InetSocketAddress(host, port), 2000)
                sock.tcpNoDelay = true
                val out = DataOutputStream(BufferedOutputStream(sock.getOutputStream()))
                connected = true
                onStatus("PC: live $host:$port")
                Log.i(TAG, "connected $host:$port")
                while (running.get()) {
                    val f = queue.poll(1, TimeUnit.SECONDS) ?: continue
                    val meta = f.meta.toByteArray(Charsets.UTF_8)
                    out.writeInt(meta.size); out.write(meta)
                    out.writeInt(f.jpeg.size); out.write(f.jpeg)
                    out.flush()
                }
            } catch (e: Exception) {
                Log.w(TAG, "conn/io err: ${e.message}")
                onStatus("PC: chưa nối ($host:$port)")
            } finally {
                connected = false
                try { sock?.close() } catch (_: Exception) {}
                queue.clear()
            }
            if (running.get()) try { Thread.sleep(2000) } catch (_: InterruptedException) {}
        }
    }
}
