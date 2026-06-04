package com.jepa.recorder

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.SystemClock
import com.hoho.android.usbserial.driver.CdcAcmSerialDriver
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import com.hoho.android.usbserial.util.SerialInputOutputManager

/**
 * Cầu USB-serial tới ESP32/dongle — KHÔNG cần root (usb-serial-for-android).
 * Đọc dòng hex → Telemetry; gửi control (bytes → hex+'\n').
 * Vai trò = đúng cái recorder.py làm với /dev/ttyACM, nhưng chạy trên Android.
 */
class SerialLink(
    private val ctx: Context,
    private val onTelemetry: (Telemetry) -> Unit,
    private val onStatus: (String) -> Unit,
) : SerialInputOutputManager.Listener {

    private var port: UsbSerialPort? = null
    private var io: SerialInputOutputManager? = null
    private val rxBuf = StringBuilder()
    @Volatile var connected = false; private set

    private val ACTION_PERM = "com.jepa.recorder.USB_PERMISSION"

    private val permReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.action == ACTION_PERM) openFirstAvailable()
        }
    }

    fun start() {
        ContextCompat_registerReceiver()
        openFirstAvailable()
    }

    fun stop() {
        try { io?.stop() } catch (_: Exception) {}
        try { port?.close() } catch (_: Exception) {}
        try { ctx.unregisterReceiver(permReceiver) } catch (_: Exception) {}
        connected = false
    }

    /** Gửi control xuống ESP32 (vd LED 0x01, hoặc [steer,throt]). */
    fun send(data: ByteArray) {
        try { port?.write(Telemetry.toHexLine(data), 200) } catch (_: Exception) {}
    }

    // ── nội bộ ────────────────────────────────────────────────────────
    private fun ContextCompat_registerReceiver() {
        val filter = IntentFilter(ACTION_PERM)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ctx.registerReceiver(permReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            ctx.registerReceiver(permReceiver, filter)
        }
    }

    private fun openFirstAvailable() {
        val usb = ctx.getSystemService(Context.USB_SERVICE) as UsbManager
        // Thử prober mặc định; nếu trống, ép CdcAcmSerialDriver cho mọi device CDC (ESP32-S3 native USB).
        var drivers = UsbSerialProber.getDefaultProber().findAllDrivers(usb)
        if (drivers.isEmpty()) {
            drivers = usb.deviceList.values.mapNotNull {
                try { CdcAcmSerialDriver(it) } catch (_: Exception) { null }
            }
        }
        if (drivers.isEmpty()) { onStatus("USB: chưa thấy ESP32 (cắm dongle?)"); return }

        val driver = drivers[0]
        val device = driver.device
        if (!usb.hasPermission(device)) {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
                PendingIntent.FLAG_MUTABLE else 0
            val pi = PendingIntent.getBroadcast(ctx, 0, Intent(ACTION_PERM).setPackage(ctx.packageName), flags)
            usb.requestPermission(device, pi)
            onStatus("USB: chờ cấp quyền…")
            return
        }
        val conn = usb.openDevice(device) ?: run { onStatus("USB: mở device lỗi"); return }
        val p = driver.ports[0]
        try {
            p.open(conn)
            p.setParameters(115200, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE)
            p.dtr = true; p.rts = true
        } catch (e: Exception) { onStatus("USB: open lỗi ${e.message}"); return }
        port = p
        io = SerialInputOutputManager(p, this).also { it.start() }
        connected = true
        onStatus("USB: kết nối OK")
    }

    override fun onNewData(data: ByteArray) {
        val t = SystemClock.elapsedRealtimeNanos()
        rxBuf.append(String(data, Charsets.US_ASCII))
        while (true) {
            val nl = rxBuf.indexOf("\n")
            if (nl < 0) break
            val line = rxBuf.substring(0, nl)
            rxBuf.delete(0, nl + 1)
            Telemetry.parseHexLine(line, t)?.let(onTelemetry)
        }
        if (rxBuf.length > 4096) rxBuf.setLength(0)   // chống dồn rác
    }

    override fun onRunError(e: Exception) {
        connected = false
        onStatus("USB: lỗi đọc ${e.message}")
    }
}
