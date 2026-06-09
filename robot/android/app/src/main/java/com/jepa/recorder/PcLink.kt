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
 * Phone = client, PC = server (tools/pc_stream_view.py / scripts/inference_loop.py). KHÔNG chặn
 * camera: hàng đợi nhỏ, đầy thì bỏ frame (live view chấp nhận rớt). Ghi cục bộ vẫn là nguồn CHÍNH.
 *
 * UPLINK (phone→PC) mỗi frame:  [u32 meta_len][meta utf-8][u32 jpeg_len][jpeg]   (big-endian).
 * DOWNLINK (PC→phone) closed-loop: khung 3 byte ``[0xA5, steer, throt]`` → relay 2 byte
 *   ``[steer, throt]`` xuống ESP32 (qua ``onAction``). Firmware chỉ áp dụng khi CH9=AUTO,
 *   nên forward luôn cũng an toàn (mode khác thì xe bỏ qua). Đọc trên thread riêng cùng socket.
 *
 * Tự kết nối lại nếu rớt. Dùng được qua Tailscale: chỉ cần PC_HOST = IP 100.x của PC.
 */
class PcLink(
    private val host: String,
    private val port: Int,
    private val onStatus: (String) -> Unit,
    private val onAction: (ByteArray) -> Unit = {},
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
                val reader = Thread { downlink(sock) }.also { it.isDaemon = true; it.start() }
                try {
                    while (running.get()) {
                        val f = queue.poll(1, TimeUnit.SECONDS) ?: continue
                        val meta = f.meta.toByteArray(Charsets.UTF_8)
                        out.writeInt(meta.size); out.write(meta)
                        out.writeInt(f.jpeg.size); out.write(f.jpeg)
                        out.flush()
                    }
                } finally {
                    reader.interrupt()
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

    /** Đọc khung downlink 3-byte ``[0xA5, steer, throt]`` từ PC → relay ``[steer, throt]`` xuống ESP32.
     *  Tự resync theo magic (bỏ byte rác). Thoát khi socket đóng (read() = -1) hoặc bị interrupt. */
    private fun downlink(sock: Socket) {
        try {
            val ins = sock.getInputStream()
            while (running.get() && !Thread.currentThread().isInterrupted) {
                val b0 = ins.read()
                if (b0 < 0) break
                if (b0 != MAGIC) continue                 // resync: chỉ nhận sau magic
                val s = ins.read(); val t = ins.read()
                if (s < 0 || t < 0) break
                onAction(byteArrayOf(s.toByte(), t.toByte()))
            }
        } catch (_: Exception) {
            // socket đóng / interrupt → kệ, loop ngoài sẽ nối lại
        }
    }

    private companion object { const val MAGIC = 0xA5 }
}
