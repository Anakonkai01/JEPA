package com.jepa.recorder

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.jepa.recorder.databinding.ActivityMainBinding
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Onboard recorder: camera điện thoại (ultrawide) + telemetry ESP32 qua USB → lưu cục bộ.
 * Thay cho OpenIPC cam + WFB. Frame timestamp = elapsedRealtime (cùng đồng hồ telemetry) → ghép chính xác.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var ui: ActivityMainBinding
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private lateinit var serial: SerialLink
    private lateinit var writer: SessionWriter
    private lateinit var pcLink: PcLink
    private lateinit var sensorLogger: SensorLogger
    private lateinit var uploader: Uploader

    @Volatile private var latest: Telemetry? = null
    // Nguồn timestamp của sensor: true = REALTIME (cùng base elapsedRealtimeNanos), false = UNKNOWN (uptime).
    @Volatile private var tsRealtime = false
    @Volatile private var usbStatus = "USB: khởi động…"
    @Volatile private var pcStatus = ""
    @Volatile private var upStatus = ""
    @Volatile private var lastRec = 0
    // Closed-loop keep-alive: PC gửi action MỚI 1 lần; phone giữ + tự gửi lại ESP32 @12Hz tại CHỖ
    // (USB tin cậy) → jitter/dropout 5G-Tailscale KHÔNG làm chạm watchdog firmware (hết giật).
    // PC im quá AUTO_STALE_MS → ngừng relay → firmware watchdog (500ms) tự về neutral (an toàn).
    @Volatile private var autoAction: ByteArray? = null
    @Volatile private var autoActionMs = 0L
    @Volatile private var autoKeepAlive = true
    private val AUTO_STALE_MS = 1000L
    private var lastSaveMs = 0L
    private var lastStreamMs = 0L
    private var lastHudMs = 0L
    private val SAVE_INTERVAL = 100L          // lưu cục bộ 10 Hz
    private val STREAM_INTERVAL = 40L         // stream PC ~25 Hz (mượt, tách khỏi nhịp lưu)
    private val TARGET_W = 640                 // hạ về 640px (V-JEPA chỉ cần 256)
    private val SHUTTER_FPS = 30               // ép phơi sáng ≤ 1/30s chống nhòe (thử 60 nếu cam hỗ trợ)
    // IP máy nhận. Mặc định = Tailscale IP LAPTOP omarchy (cả LAN lẫn 5G); LAN-only "192.168.100.41";
    // PC cũ 5070ti = 100.110.165.40. ĐỔI NGAY TRONG APP: nhấn-giữ ô status (lưu vào SharedPreferences,
    // không cần build lại). `hostname -I` (LAN) hoặc `tailscale ip -4` (5G) trên máy nhận.
    private val DEFAULT_PC_HOST = "100.84.196.41"
    private lateinit var pcHost: String
    private val PC_PORT = 5055         // live view (pc_stream_view.py)
    private val UPLOAD_PORT = 5056     // gửi nguyên session (pc_receiver.py)
    private fun prefs() = getSharedPreferences("jepa", MODE_PRIVATE)

    // FPS đếm thô
    private var fpsCount = 0; private var fpsT = 0L; private var fps = 0f

    private val camPerm = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (it) startCamera() else toast("Cần quyền camera")
    }

    private val locPerm = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (it) sensorLogger.startGps() else toast("Không có quyền GPS — vẫn ghi IMU")
    }

    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        ui = ActivityMainBinding.inflate(layoutInflater)
        setContentView(ui.root)

        pcHost = prefs().getString("pc_host", DEFAULT_PC_HOST) ?: DEFAULT_PC_HOST
        writer = SessionWriter(this)
        // onAction = closed-loop downlink: PC gửi [steer,throt] → relay xuống ESP32 (firmware chỉ
        // áp dụng khi CH9=AUTO). 'serial' gán bên dưới trước pcLink.start() nên an toàn.
        pcLink = PcLink(pcHost, PC_PORT,
            onStatus = { s -> pcStatus = s; runOnUiThread { updateHud() } },
            onAction = { bytes -> autoAction = bytes; autoActionMs = SystemClock.elapsedRealtime() })
        uploader = Uploader(pcHost, UPLOAD_PORT, cacheDir, onStatus = { s -> upStatus = s; runOnUiThread { updateHud() } })
        sensorLogger = SensorLogger(this, writer)
        serial = SerialLink(this, onTelemetry = { t ->
            latest = t
            handleAutoRec(t)
            if (writer.active) writer.logTelem(t)
        }, onStatus = { s -> usbStatus = s; runOnUiThread { updateHud() } })

        ui.recBtn.setOnClickListener { toggleRec() }
        ui.dimBtn.setOnClickListener { setDim(true) }
        ui.blackout.setOnClickListener { setDim(false) }
        ui.sessionsBtn.setOnClickListener { startActivity(Intent(this, SessionListActivity::class.java)) }
        ui.status.setOnLongClickListener { editPcHost(); true }   // nhấn-giữ status = đổi IP PC

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED) startCamera()
        else camPerm.launch(Manifest.permission.CAMERA)

        serial.start()
        startAutoRelay()
        pcLink.start()
        uploader.start()
        uploader.enqueuePending(File(getExternalFilesDir(null), "sessions"))  // bù session chưa gửi (PC từng tắt)
        sensorLogger.start()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED) sensorLogger.startGps()
        else locPerm.launch(Manifest.permission.ACCESS_FINE_LOCATION)
    }

    /** Thread keep-alive: gửi lại action cuối từ PC xuống ESP32 @~12Hz qua USB (đường tin cậy),
     *  hấp thụ jitter WAN. Ngừng nếu PC im > AUTO_STALE_MS → firmware watchdog tự về neutral. */
    private fun startAutoRelay() {
        Thread {
            while (autoKeepAlive) {
                val a = autoAction
                if (a != null && ::serial.isInitialized &&
                    SystemClock.elapsedRealtime() - autoActionMs < AUTO_STALE_MS) {
                    serial.send(a)
                }
                try { Thread.sleep(80) } catch (_: InterruptedException) { break }   // ~12Hz
            }
        }.apply { isDaemon = true }.start()
    }

    /** Nhấn-giữ status → đổi IP PC nhận (stream + upload). Lưu prefs rồi tạo lại Activity để
     *  PcLink/Uploader nối lại host mới — khỏi build lại app khi đổi máy/mạng. */
    private fun editPcHost() {
        val et = android.widget.EditText(this).apply {
            setText(pcHost); hint = "IP PC ($DEFAULT_PC_HOST)"; setSingleLine()
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("IP máy PC nhận (port $PC_PORT/$UPLOAD_PORT)").setView(et)
            .setPositiveButton("Lưu") { _, _ ->
                val h = et.text.toString().trim()
                if (h.isNotEmpty() && h != pcHost) {
                    prefs().edit().putString("pc_host", h).apply()
                    toast("PC = $h — khởi động lại link…")
                    recreate()
                }
            }
            .setNeutralButton("Mặc định") { _, _ ->
                prefs().edit().remove("pc_host").apply(); toast("PC = $DEFAULT_PC_HOST"); recreate()
            }
            .setNegativeButton("Huỷ", null).show()
    }

    /** Tự bật/tắt ghi theo cờ rec (công tắc CH10 trên remote) — edge-triggered. */
    private fun handleAutoRec(t: Telemetry) {
        if (t.rec == 1 && lastRec == 0 && !writer.active) {
            writer.start()
            runOnUiThread { ui.recBtn.text = "■ AUTO-REC (CH10)" }
        } else if (t.rec == 0 && lastRec == 1 && writer.active) {
            val dir = writer.dir
            val msg = writer.stop()
            dir?.let { uploader.enqueue(it) }
            runOnUiThread { ui.recBtn.text = "● chờ CH10"; toast("Dừng — $msg") }
        }
        lastRec = t.rec
    }

    private fun telemFresh(): Boolean {
        val t = latest ?: return false
        val ageMs = (SystemClock.elapsedRealtimeNanos() - t.tNanos) / 1_000_000
        return ageMs in 0L..500L
    }

    /** Nút màn hình = fallback THỦ CÔNG, chỉ khi mất telemetry (có telem thì CH10 cầm trịch). */
    private fun toggleRec() {
        if (telemFresh()) { toast("Đang theo CH10 — gạt công tắc record trên remote"); return }
        if (writer.active) {
            val dir = writer.dir
            val msg = writer.stop()
            dir?.let { uploader.enqueue(it) }
            toast("Dừng — $msg")
            ui.recBtn.text = "● REC"
        } else {
            writer.start()
            ui.recBtn.text = "■ STOP (thủ công)"
        }
    }

    /** Tiết kiệm pin: phủ đen toàn màn + hạ độ sáng về tối thiểu (AMOLED ≈ tắt pixel). Ghi vẫn chạy. */
    private fun setDim(on: Boolean) {
        ui.blackout.visibility = if (on) View.VISIBLE else View.GONE
        val lp = window.attributes
        lp.screenBrightness = if (on) 0.004f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        window.attributes = lp
        if (on) toast("Màn tối — chạm màn hình để sáng lại (vẫn đang ghi)")
    }

    @OptIn(ExperimentalCamera2Interop::class)
    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            val provider = future.get()

            // Chọn lens BACK có tiêu cự nhỏ nhất = ULTRAWIDE (gần FPV). Fallback = cam chính.
            val selector = CameraSelector.Builder()
                .requireLensFacing(CameraSelector.LENS_FACING_BACK)
                .addCameraFilter { infos ->
                    val best = infos.minByOrNull { ci ->
                        val f = Camera2CameraInfo.from(ci)
                            .getCameraCharacteristic(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                        f?.minOrNull() ?: Float.MAX_VALUE
                    }
                    if (best != null) listOf(best) else infos
                }
                .build()

            val preview = Preview.Builder().build()
                .also { it.setSurfaceProvider(ui.preview.surfaceProvider) }

            val analysisBuilder = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .setTargetResolution(Size(1280, 720))
            // Khóa màn trập nhanh chống nhòe: giữ AE auto (tự bù sáng) nhưng ép khung hình
            // ≥ SHUTTER_FPS → thời gian phơi sáng ≤ 1/SHUTTER_FPS. Ngoài trời sẽ tự về rất ngắn.
            Camera2Interop.Extender(analysisBuilder).setCaptureRequestOption(
                CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, Range(SHUTTER_FPS, SHUTTER_FPS))
            val analysis = analysisBuilder.build()
                .also { it.setAnalyzer(cameraExecutor, ::onFrame) }

            try {
                provider.unbindAll()
                val camera = provider.bindToLifecycle(this, selector, preview, analysis)
                // Xác định nguồn timestamp sensor → biết cách quy mốc phơi sáng về đồng hồ elapsedRealtime.
                val src = Camera2CameraInfo.from(camera.cameraInfo)
                    .getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE)
                tsRealtime = (src == CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME)
                android.util.Log.i("JEPA", "SENSOR_INFO_TIMESTAMP_SOURCE=$src realtime=$tsRealtime")
            } catch (e: Exception) {
                toast("Camera lỗi: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun onFrame(image: ImageProxy) {
        val now = SystemClock.elapsedRealtime()
        // đếm fps
        fpsCount++
        if (now - fpsT >= 1000) { fps = fpsCount * 1000f / (now - fpsT); fpsCount = 0; fpsT = now }

        // δ_cam: độ trễ từ lúc phơi sáng sensor → callback này. Quy mốc phơi sáng về đồng hồ elapsedRealtime
        // (cùng đồng hồ telemetry) bằng capMs → frame lưu đúng thời điểm cảnh thật, hết lệch action.
        val sensorNs = image.imageInfo.timestamp
        val nowSensorNs = if (tsRealtime) SystemClock.elapsedRealtimeNanos() else System.nanoTime()
        val dcamMs = (nowSensorNs - sensorNs) / 1_000_000.0
        val capMs = if (dcamMs in 0.0..500.0) now - dcamMs.toLong() else now   // chặn timestamp bất thường

        val needSave = writer.active && now - lastSaveMs >= SAVE_INTERVAL
        val needStream = pcLink.connected && now - lastStreamMs >= STREAM_INTERVAL
        if (needSave || needStream) {
            try {
                val jpeg = imageToJpeg(image)
                if (needSave) { writer.saveFrame(jpeg, capMs, dcamMs, latest); lastSaveMs = now }
                if (needStream) { pcLink.offer(jpeg, buildMeta(now)); lastStreamMs = now }
            } catch (_: Exception) {}
        }
        image.close()
        if (now - lastHudMs >= 200) { lastHudMs = now; updateHud() }   // HUD ~5Hz, đừng spam mỗi frame
    }

    /** Meta JSON kèm mỗi frame stream về PC (Locale.US để JSON hợp lệ). Gồm cả STATE cảm biến
     *  (gyro/accel/rotvec + GPS speed) → closed-loop trên PC có đủ [speed,gx..gz,ax..az,rx..rz]
     *  cho world model (khớp DEFAULT_COLUMNS trong src/jepa_wm/data/state.py). */
    private fun buildMeta(now: Long): String {
        val t = latest
        val st = "%.4f".format(Locale.US, t?.steer ?: 0f)
        val th = "%.4f".format(Locale.US, t?.throt ?: 0f)
        val g = sensorLogger.gyro; val a = sensorLogger.accel; val r = sensorLogger.rot
        fun f(v: Float) = "%.5f".format(Locale.US, v)
        return "{\"t_ms\":$now,\"idx\":${writer.count},\"steering\":$st,\"throttle\":$th," +
            "\"seq\":${t?.seq ?: -1L},\"esp_ms\":${t?.espMs ?: -1L},\"mode\":${t?.mode ?: -1}," +
            "\"rec\":${t?.rec ?: 0},\"recording\":${writer.active}," +
            "\"speed\":${f(sensorLogger.gpsSpeed)}," +
            "\"lat\":${"%.7f".format(Locale.US, sensorLogger.gpsLat)}," +
            "\"lon\":${"%.7f".format(Locale.US, sensorLogger.gpsLon)}," +
            "\"gx\":${f(g[0])},\"gy\":${f(g[1])},\"gz\":${f(g[2])}," +
            "\"ax\":${f(a[0])},\"ay\":${f(a[1])},\"az\":${f(a[2])}," +
            "\"rx\":${f(r[0])},\"ry\":${f(r[1])},\"rz\":${f(r[2])}}"
    }

    private fun updateHud() {
        val t = latest
        val ageMs = if (t != null) (SystemClock.elapsedRealtimeNanos() - t.tNanos) / 1_000_000 else -1L
        val telemTxt = if (t != null && ageMs in 0L..500L)
            "telem OK  mode:${t.mode}  steer:${"%+.2f".format(Locale.US, t.steer)} throt:${"%+.2f".format(Locale.US, t.throt)}" +
                (t.rssi?.let { "  ESP:${it}dBm" } ?: "")
        else "NO TELEM · $usbStatus"
        val rec = if (writer.active) "● REC ${writer.count}" else "STANDBY"
        runOnUiThread {
            ui.status.text = "$rec  v0.3🤖  cam:${"%.0f".format(Locale.US, fps)}fps\n$telemTxt\n$pcStatus  $upStatus\nPC=$pcHost (giữ status để đổi)"
        }
    }

    /** RGBA_8888 ImageProxy → xoay đúng chiều → hạ 640px → JPEG. */
    private fun imageToJpeg(image: ImageProxy): ByteArray {
        val plane = image.planes[0]
        val buffer = plane.buffer.apply { rewind() }
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val w = image.width; val h = image.height
        val rowPadding = rowStride - pixelStride * w
        var bmp = Bitmap.createBitmap(w + rowPadding / pixelStride, h, Bitmap.Config.ARGB_8888)
        bmp.copyPixelsFromBuffer(buffer)
        if (rowPadding != 0) bmp = Bitmap.createBitmap(bmp, 0, 0, w, h)

        val deg = image.imageInfo.rotationDegrees
        if (deg != 0) {
            val m = Matrix().apply { postRotate(deg.toFloat()) }
            bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
        }
        val tw = TARGET_W
        val th = (bmp.height.toLong() * tw / bmp.width).toInt().coerceAtLeast(1)
        val scaled = Bitmap.createScaledBitmap(bmp, tw, th, true)

        val baos = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 85, baos)
        return baos.toByteArray()
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    override fun onResume() {
        super.onResume()
        if (::serial.isInitialized) serial.rescan()
    }

    override fun onDestroy() {
        super.onDestroy()
        autoKeepAlive = false
        if (writer.active) writer.stop()
        serial.stop()
        pcLink.stop()
        uploader.stop()
        sensorLogger.stop()
        cameraExecutor.shutdown()
    }
}
