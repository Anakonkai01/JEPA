package com.jepa.recorder

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CaptureRequest
import android.os.Bundle
import android.os.SystemClock
import android.util.Range
import android.util.Size
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
    @Volatile private var usbStatus = "USB: khởi động…"
    @Volatile private var pcStatus = ""
    @Volatile private var upStatus = ""
    @Volatile private var lastRec = 0
    private var lastSaveMs = 0L
    private var lastStreamMs = 0L
    private val SAVE_INTERVAL = 100L          // lưu cục bộ 10 Hz
    private val STREAM_INTERVAL = 40L         // stream PC ~25 Hz (mượt, tách khỏi nhịp lưu)
    private val TARGET_W = 640                 // hạ về 640px (V-JEPA chỉ cần 256)
    private val SHUTTER_FPS = 30               // ép phơi sáng ≤ 1/30s chống nhòe (thử 60 nếu cam hỗ trợ)
    // ĐẶT IP máy nhận: cùng LAN dùng `hostname -I`; qua Tailscale (phone 5G) dùng IP 100.x (`tailscale ip -4`).
    private val PC_HOST = "100.84.196.41"    // Tailscale IP của LAPTOP omarchy (chạy cả LAN lẫn 5G). LAN-only: "192.168.100.41". PC cũ 5070ti = 100.110.165.40
    private val PC_PORT = 5055         // live view (pc_stream_view.py)
    private val UPLOAD_PORT = 5056     // gửi nguyên session (pc_receiver.py)

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

        writer = SessionWriter(this)
        pcLink = PcLink(PC_HOST, PC_PORT, onStatus = { s -> pcStatus = s; runOnUiThread { updateHud() } })
        uploader = Uploader(PC_HOST, UPLOAD_PORT, cacheDir, onStatus = { s -> upStatus = s; runOnUiThread { updateHud() } })
        sensorLogger = SensorLogger(this, writer)
        serial = SerialLink(this, onTelemetry = { t ->
            latest = t
            handleAutoRec(t)
            if (writer.active) writer.logTelem(t)
        }, onStatus = { s -> usbStatus = s; runOnUiThread { updateHud() } })

        ui.recBtn.setOnClickListener { toggleRec() }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED) startCamera()
        else camPerm.launch(Manifest.permission.CAMERA)

        serial.start()
        pcLink.start()
        uploader.start()
        uploader.enqueuePending(File(getExternalFilesDir(null), "sessions"))  // bù session chưa gửi (PC từng tắt)
        sensorLogger.start()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED) sensorLogger.startGps()
        else locPerm.launch(Manifest.permission.ACCESS_FINE_LOCATION)
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
                provider.bindToLifecycle(this, selector, preview, analysis)
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

        val needSave = writer.active && now - lastSaveMs >= SAVE_INTERVAL
        val needStream = pcLink.connected && now - lastStreamMs >= STREAM_INTERVAL
        if (needSave || needStream) {
            try {
                val jpeg = imageToJpeg(image)
                if (needSave) { writer.saveFrame(jpeg, now, latest); lastSaveMs = now }
                if (needStream) { pcLink.offer(jpeg, buildMeta(now)); lastStreamMs = now }
            } catch (_: Exception) {}
        }
        image.close()
        updateHud()
    }

    /** Meta JSON kèm mỗi frame stream về PC (Locale.US để JSON hợp lệ). */
    private fun buildMeta(now: Long): String {
        val t = latest
        val st = "%.4f".format(Locale.US, t?.steer ?: 0f)
        val th = "%.4f".format(Locale.US, t?.throt ?: 0f)
        return "{\"t_ms\":$now,\"idx\":${writer.count},\"steering\":$st,\"throttle\":$th," +
            "\"seq\":${t?.seq ?: -1L},\"esp_ms\":${t?.espMs ?: -1L},\"mode\":${t?.mode ?: -1}," +
            "\"rec\":${t?.rec ?: 0},\"recording\":${writer.active}}"
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
            ui.status.text = "$rec   cam:${"%.0f".format(Locale.US, fps)}fps\n$telemTxt\n$pcStatus  $upStatus"
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
        if (writer.active) writer.stop()
        serial.stop()
        pcLink.stop()
        uploader.stop()
        sensorLogger.stop()
        cameraExecutor.shutdown()
    }
}
