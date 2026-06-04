package com.jepa.recorder

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.hardware.camera2.CameraCharacteristics
import android.os.Bundle
import android.os.SystemClock
import android.util.Size
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.jepa.recorder.databinding.ActivityMainBinding
import java.io.ByteArrayOutputStream
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

    @Volatile private var latest: Telemetry? = null
    private var lastSaveMs = 0L
    private val SAVE_INTERVAL = 100L          // 10 Hz
    private val TARGET_W = 640                 // hạ về 640px (V-JEPA chỉ cần 256)

    // FPS đếm thô
    private var fpsCount = 0; private var fpsT = 0L; private var fps = 0f

    private val camPerm = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (it) startCamera() else toast("Cần quyền camera")
    }

    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        ui = ActivityMainBinding.inflate(layoutInflater)
        setContentView(ui.root)

        writer = SessionWriter(this)
        serial = SerialLink(this, onTelemetry = { t ->
            latest = t
            if (writer.active) writer.logTelem(t)
        }, onStatus = { runOnUiThread { /* trạng thái USB gộp vào HUD */ } })

        ui.recBtn.setOnClickListener { toggleRec() }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED) startCamera()
        else camPerm.launch(Manifest.permission.CAMERA)

        serial.start()
    }

    private fun toggleRec() {
        if (writer.active) {
            val msg = writer.stop()
            toast("Dừng — $msg")
            ui.recBtn.text = "● REC"
        } else {
            writer.start()
            ui.recBtn.text = "■ STOP"
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

            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .setTargetResolution(Size(1280, 720))
                .build()
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

        if (writer.active && now - lastSaveMs >= SAVE_INTERVAL) {
            try {
                val jpeg = imageToJpeg(image)
                writer.saveFrame(jpeg, now, latest)
                lastSaveMs = now
            } catch (_: Exception) {}
        }
        image.close()
        updateHud(now)
    }

    private fun updateHud(now: Long) {
        val t = latest
        val ageMs = if (t != null) (SystemClock.elapsedRealtimeNanos() - t.tNanos) / 1_000_000 else -1
        val telemTxt = if (t != null && ageMs in 0..500)
            "telem OK  mode:${t.mode}  steer:${"%+.2f".format(t.steer)} throt:${"%+.2f".format(t.throt)}" +
                (t.rssi?.let { "  ESP:${it}dBm" } ?: "")
        else "NO TELEM (cắm dongle?)"
        val rec = if (writer.active) "● REC ${writer.count}" else "STANDBY"
        runOnUiThread {
            ui.status.text = "$rec   cam:${"%.0f".format(fps)}fps\n$telemTxt"
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

    override fun onDestroy() {
        super.onDestroy()
        if (writer.active) writer.stop()
        serial.stop()
        cameraExecutor.shutdown()
    }
}
