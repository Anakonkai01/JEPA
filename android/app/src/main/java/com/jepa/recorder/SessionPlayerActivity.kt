package com.jepa.recorder

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.SeekBar
import androidx.appcompat.app.AppCompatActivity
import com.jepa.recorder.databinding.ActivitySessionPlayerBinding
import java.io.File
import java.util.Locale

/** Xem lại 1 session: tua/phát frame + overlay steer/throttle/mode/δ_cam (đọc actions.csv). */
class SessionPlayerActivity : AppCompatActivity() {

    companion object { const val EXTRA_DIR = "dir" }

    private lateinit var ui: ActivitySessionPlayerBinding
    private lateinit var dir: File
    private var n = 0
    private val tArr = ArrayList<Long>()
    private val steer = ArrayList<Float>()
    private val throt = ArrayList<Float>()
    private val mode = ArrayList<Int>()
    private val dcam = ArrayList<Float>()
    private var idx = 0
    private var playing = false
    private val handler = Handler(Looper.getMainLooper())

    private val tick = object : Runnable {
        override fun run() {
            if (!playing) return
            if (idx < n - 1) {
                idx++; ui.seek.progress = idx; render(idx); handler.postDelayed(this, 125)  // ~8fps
            } else setPlaying(false)
        }
    }

    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        ui = ActivitySessionPlayerBinding.inflate(layoutInflater)
        setContentView(ui.root)
        dir = File(intent.getStringExtra(EXTRA_DIR) ?: "")
        loadActions()
        ui.seek.max = if (n > 0) n - 1 else 0
        ui.seek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, p: Int, fromUser: Boolean) {
                if (fromUser) { idx = p; render(p) }
            }
            override fun onStartTrackingTouch(sb: SeekBar) { setPlaying(false) }
            override fun onStopTrackingTouch(sb: SeekBar) {}
        })
        ui.playBtn.setOnClickListener { setPlaying(!playing) }
        if (n > 0) render(0) else ui.overlay.text = "Không đọc được actions.csv"
    }

    private fun loadActions() {
        val f = File(dir, "actions.csv")
        if (!f.exists()) return
        f.useLines { lines ->
            lines.drop(1).forEach { ln ->
                val p = ln.split(',')
                if (p.size >= 4) {
                    tArr.add(p[1].toLongOrNull() ?: 0L)
                    steer.add(p[2].toFloatOrNull() ?: 0f)
                    throt.add(p[3].toFloatOrNull() ?: 0f)
                    mode.add(if (p.size >= 7) p[6].toIntOrNull() ?: 0 else 0)
                    dcam.add(if (p.size >= 8) p[7].toFloatOrNull() ?: 0f else 0f)
                }
            }
        }
        n = steer.size
    }

    private fun setPlaying(on: Boolean) {
        playing = on && n > 0
        ui.playBtn.text = if (playing) "❚❚" else "▶"
        handler.removeCallbacks(tick)
        if (playing) {
            if (idx >= n - 1) idx = 0
            handler.postDelayed(tick, 125)
        }
    }

    private fun render(i: Int) {
        val bmp = BitmapFactory.decodeFile(File(dir, "frames/%06d.jpg".format(i + 1)).absolutePath)
        if (bmp != null) {
            val out = bmp.copy(Bitmap.Config.ARGB_8888, true)
            bmp.recycle()
            drawBars(out, i)
            ui.frame.setImageBitmap(out)
        }
        val t0 = if (tArr.isNotEmpty()) tArr[0] else 0L
        ui.overlay.text = String.format(Locale.US,
            "%d/%d  t+%.2fs  mode=%d\nsteer %+.3f   ga %+.3f   δ%.0fms",
            i + 1, n, (tArr.getOrElse(i) { 0L } - t0) / 1000.0, mode.getOrElse(i) { 0 },
            steer.getOrElse(i) { 0f }, throt.getOrElse(i) { 0f }, dcam.getOrElse(i) { 0f })
    }

    /** Vẽ thanh steer (ngang, gốc giữa) + throttle (dọc, ×3 cho dễ thấy) lên frame. */
    private fun drawBars(bmp: Bitmap, i: Int) {
        val c = Canvas(bmp); val w = bmp.width.toFloat(); val h = bmp.height.toFloat()
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        val track = 0xAA000000.toInt(); val white = 0xFFFFFFFF.toInt()
        // steering: ngang sát đáy
        val cx = w / 2f; val by = h - 14f; val half = w * 0.38f
        val sv = steer.getOrElse(i) { 0f }.coerceIn(-1f, 1f)
        p.color = track; c.drawRect(cx - half, by - 5, cx + half, by + 5, p)
        p.color = 0xFFFFCC00.toInt()
        val sx = cx + sv * half
        c.drawRect(minOf(cx, sx), by - 5, maxOf(cx, sx), by + 5, p)
        p.color = white; c.drawRect(cx - 1, by - 9, cx + 1, by + 9, p)
        // throttle: dọc bên phải
        val tx = w - 14f; val cyt = h / 2f; val vh = h * 0.3f
        val tv = (throt.getOrElse(i) { 0f } * 3f).coerceIn(-1f, 1f)
        p.color = track; c.drawRect(tx - 5, cyt - vh, tx + 5, cyt + vh, p)
        p.color = if (tv >= 0) 0xFF33CC66.toInt() else 0xFFFF4444.toInt()
        val ty = cyt - tv * vh
        c.drawRect(tx - 5, minOf(cyt, ty), tx + 5, maxOf(cyt, ty), p)
        p.color = white; c.drawRect(tx - 9, cyt - 1, tx + 9, cyt + 1, p)
    }

    override fun onPause() { super.onPause(); setPlaying(false) }
}
