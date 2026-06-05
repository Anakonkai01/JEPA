package com.jepa.recorder

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.hoho.android.usbserial.driver.CdcAcmSerialDriver
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import com.hoho.android.usbserial.util.SerialInputOutputManager

/**
 * Cầu USB-serial tới ESP32/dongle — KHÔNG cần root (usb-serial-for-android).
 * Đọc dòng hex → Telemetry; gửi control (bytes → hex+'\n').
 * Vai trò = đúng cái recorder.py làm với /dev/ttyACM, nhưng chạy trên Android.
 *
 * Telemetry CHỈ ra ở cổng UART (chip cầu, hiện "USB Single Serial"), KHÔNG ra
 * cổng native ("USB JTAG/serial debug unit"). Log VID/PID để soi bằng `adb logcat`.
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
    private val TAG = "SerialLink"

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            when (i.action) {
                ACTION_PERM, UsbManager.ACTION_USB_DEVICE_ATTACHED -> openFirstAvailable()
                UsbManager.ACTION_USB_DEVICE_DETACHED -> { close(); status("USB: đã rút thiết bị") }
            }
        }
    }

    fun start() {
        registerReceiver()
        openFirstAvailable()
    }

    /** Gọi từ Activity.onResume — quét lại nếu chưa kết nối (cắm-lại không cần mở lại app). */
    fun rescan() { if (!connected) openFirstAvailable() }

    fun stop() {
        close()
        try { ctx.unregisterReceiver(receiver) } catch (_: Exception) {}
    }

    /** Gửi control xuống ESP32 (vd LED 0x01, hoặc [steer,throt]). */
    fun send(data: ByteArray) {
        try { port?.write(Telemetry.toHexLine(data), 200) } catch (_: Exception) {}
    }

    // ── nội bộ ────────────────────────────────────────────────────────
    private fun status(s: String) { Log.i(TAG, s); onStatus(s) }

    private fun close() {
        try { io?.stop() } catch (_: Exception) {}
        try { port?.close() } catch (_: Exception) {}
        io = null; port = null; connected = false
    }

    private fun registerReceiver() {
        val filter = IntentFilter(ACTION_PERM).apply {
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            ctx.registerReceiver(receiver, filter)
        }
    }

    private fun openFirstAvailable() {
        if (connected) return
        val usb = ctx.getSystemService(Context.USB_SERVICE) as UsbManager

        // Soi mọi thiết bị USB nhìn thấy (xem bằng: adb logcat -s SerialLink)
        val devs = usb.deviceList.values.toList()
        Log.i(TAG, "USB devices thấy được: ${devs.size}")
        devs.forEach {
            Log.i(TAG, "  vid=0x%04X pid=0x%04X %s".format(it.vendorId, it.productId, it.productName ?: "?"))
        }

        // Prober mặc định (CH34x/CP210x/FTDI/CDC). Trống → ép CdcAcm cho mọi device.
        var drivers = UsbSerialProber.getDefaultProber().findAllDrivers(usb)
        if (drivers.isEmpty()) {
            drivers = devs.mapNotNull { try { CdcAcmSerialDriver(it) } catch (_: Exception) { null } }
        }
        if (drivers.isEmpty()) {
            status("USB: chưa thấy serial — cắm cổng 'USB Single Serial' (${devs.size} dev)")
            return
        }

        val driver = drivers[0]
        val device = driver.device
        Log.i(TAG, "Chọn ${driver.javaClass.simpleName} cho vid=0x%04X pid=0x%04X"
            .format(device.vendorId, device.productId))

        if (!usb.hasPermission(device)) {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
                PendingIntent.FLAG_MUTABLE else 0
            val pi = PendingIntent.getBroadcast(ctx, 0, Intent(ACTION_PERM).setPackage(ctx.packageName), flags)
            usb.requestPermission(device, pi)
            status("USB: chờ cấp quyền…")
            return
        }
        val conn = usb.openDevice(device) ?: run { status("USB: mở device lỗi"); return }
        val p = driver.ports[0]
        try {
            p.open(conn)
            p.setParameters(115200, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE)
            // KHÔNG ép RTS: trên cổng UART có mạch auto-reset, RTS có thể giữ ESP32 trong reset.
            try { p.dtr = true } catch (_: Exception) {}
            try { p.rts = false } catch (_: Exception) {}
        } catch (e: Exception) { status("USB: open lỗi ${e.message}"); close(); return }
        port = p
        io = SerialInputOutputManager(p, this).also { it.start() }
        connected = true
        status("USB: kết nối OK (vid=0x%04X)".format(device.vendorId))
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
        Log.w(TAG, "onRunError ${e.message}")
        connected = false
        status("USB: lỗi đọc ${e.message}")
    }
}
