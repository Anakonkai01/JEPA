package com.jepa.recorder

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log

/**
 * Ghi cảm biến điện thoại vào session đang mở: accelerometer, gyroscope, rotation-vector, GPS.
 * Cùng đồng hồ `elapsedRealtime` với frame/telemetry → align offline được. Mỗi loại 1 CSV.
 * Chỉ ghi khi writer.active (gate) → standby không tốn ghi. IMU không cần quyền; GPS cần location.
 * Sự kiện IMU đẩy về 1 HandlerThread riêng → không kẹt main thread.
 */
class SensorLogger(
    private val ctx: Context,
    private val writer: SessionWriter,
) : SensorEventListener {

    private val sm = ctx.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val sensorThread = HandlerThread("jepa-sensors").also { it.start() }
    private val handler = Handler(sensorThread.looper)
    private val TAG = "SensorLogger"

    private val locListener = object : LocationListener {
        override fun onLocationChanged(loc: Location) {
            if (writer.active) writer.logGps(SystemClock.elapsedRealtime(), loc)
        }
        override fun onProviderDisabled(p: String) {}
        override fun onProviderEnabled(p: String) {}
        @Deprecated("API cũ") override fun onStatusChanged(p: String?, s: Int, e: Bundle?) {}
    }

    /** Đăng ký IMU (accel/gyro/rotvec) — không cần quyền. */
    fun start() {
        val d = SensorManager.SENSOR_DELAY_GAME       // ~50Hz
        sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sm.registerListener(this, it, d, handler) }
        sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let { sm.registerListener(this, it, d, handler) }
        sm.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)?.let { sm.registerListener(this, it, d, handler) }
    }

    /** Bật GPS — gọi SAU khi đã có quyền ACCESS_FINE_LOCATION. */
    fun startGps() {
        try {
            lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 200L, 0f, locListener)
            Log.i(TAG, "GPS updates ON")
        } catch (e: SecurityException) {
            Log.w(TAG, "GPS thiếu quyền: ${e.message}")
        } catch (e: Exception) {
            Log.w(TAG, "GPS lỗi: ${e.message}")
        }
    }

    fun stop() {
        sm.unregisterListener(this)
        try { lm.removeUpdates(locListener) } catch (_: Exception) {}
        sensorThread.quitSafely()
    }

    override fun onSensorChanged(e: SensorEvent) {
        if (!writer.active) return
        val t = SystemClock.elapsedRealtime()
        when (e.sensor.type) {
            Sensor.TYPE_ACCELEROMETER   -> writer.logAccel(t, e.values)
            Sensor.TYPE_GYROSCOPE       -> writer.logGyro(t, e.values)
            Sensor.TYPE_ROTATION_VECTOR -> writer.logRot(t, e.values)
        }
    }

    override fun onAccuracyChanged(s: Sensor?, a: Int) {}
}
