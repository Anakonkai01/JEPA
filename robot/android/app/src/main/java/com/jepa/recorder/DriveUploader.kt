package com.jepa.recorder

import android.accounts.Account
import android.content.Context
import android.util.Log
import com.google.android.gms.auth.GoogleAuthUtil
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okio.source
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * Upload NGUYÊN session (zip) lên Google Drive cá nhân (folder "JEPA") — REST trực tiếp qua OkHttp,
 * không kéo lib google-api-services-drive. Token lấy từ tài khoản đã đăng nhập GoogleSignIn (scope
 * drive.file). Hàng đợi bền giống Uploader.kt: lỗi mạng/token → thử lại. Marker `.drive_uploaded`.
 * Đặt `account` sau khi đăng nhập (GoogleSignInAccount.account).
 */
class DriveUploader(
    private val ctx: Context,
    private val onStatus: (String) -> Unit,
) {
    @Volatile var account: Account? = null

    private val queue = LinkedBlockingQueue<File>()
    @Volatile private var running = false
    private var thread: Thread? = null
    private val TAG = "DriveUploader"
    private val SCOPE = "oauth2:https://www.googleapis.com/auth/drive.file"
    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(0, TimeUnit.SECONDS)     // upload lớn → không giới hạn ghi
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    fun start() {
        if (running) return
        running = true
        thread = Thread { loop() }.also { it.isDaemon = true; it.start() }
    }

    fun stop() { running = false; thread?.interrupt() }

    fun enqueue(dir: File) { queue.offer(dir); onStatus("Drive: chờ gửi ${queue.size}") }

    /** Xếp hàng mọi session chưa lên Drive (thiếu marker .drive_uploaded). */
    fun enqueuePending(sessionsRoot: File) {
        val dirs = sessionsRoot.listFiles { f -> f.isDirectory && f.name.startsWith("session_") } ?: return
        var k = 0
        for (d in dirs.sortedBy { it.name }) {
            if (!File(d, ".drive_uploaded").exists() && File(d, "actions.csv").exists()) { queue.offer(d); k++ }
        }
        if (k > 0) onStatus("Drive: $k session chờ gửi")
    }

    private fun loop() {
        while (running) {
            val dir = try { queue.take() } catch (e: InterruptedException) { break }
            val acc = account
            if (acc == null) {
                onStatus("Drive: chưa đăng nhập Google")
                queue.offer(dir)
                try { Thread.sleep(4000) } catch (_: InterruptedException) { break }
                continue
            }
            val ok = try { upload(dir, acc) } catch (e: Exception) { Log.w(TAG, "fail: ${e.message}"); false }
            if (ok) onStatus("Drive OK: ${dir.name}")
            else if (running) {
                queue.offer(dir); onStatus("Drive: lỗi, thử lại (${queue.size})")
                try { Thread.sleep(5000) } catch (_: InterruptedException) { break }
            }
        }
    }

    private fun token(acc: Account): String = GoogleAuthUtil.getToken(ctx, acc, SCOPE)

    private fun upload(dir: File, acc: Account): Boolean {
        if (!dir.exists()) return true
        if (File(dir, ".drive_uploaded").exists()) return true
        var tok = token(acc)
        var folderId = ensureFolder(tok)
        if (folderId == null) {                       // token có thể hết hạn → làm mới 1 lần
            GoogleAuthUtil.clearToken(ctx, tok); tok = token(acc); folderId = ensureFolder(tok)
        }
        if (folderId == null) return false
        val zipName = "${dir.name}.zip"
        // Chống upload TRÙNG: nếu lần trước PUT xong nhưng app chết trước khi ghi marker, file đã
        // có trên Drive → chỉ ghi marker rồi thôi (đỡ tốn 5G + đỡ tạo bản trùng tên trên Drive).
        if (fileExists(tok, zipName, folderId)) {
            File(dir, ".drive_uploaded").createNewFile()
            return true
        }
        // Zip GIỮ LẠI giữa các lần retry (chỉ xoá khi gửi xong): resume byte-offset cần phần đã
        // gửi khớp bit-bit với phần sắp gửi. (Zips ghi entry time = mtime → rezip cũng same-bytes.)
        val zip = File(ctx.cacheDir, zipName)
        if (!zip.exists() || zip.length() == 0L) Zips.zipDir(dir, zip)
        // URI resumable lưu cạnh session → app chết / rớt mạng giữa zip lớn → lần sau gửi TIẾP
        // từ byte đã nhận (không phải từ 0). URI Google sống ~1 tuần; hết hạn thì init lại.
        val uriFile = File(dir, ".drive_upload_uri")
        var uri = if (uriFile.exists()) uriFile.readText().trim().ifEmpty { null } else null
        if (uri == null) {
            uri = initResumable(tok, zipName, folderId) ?: return false
            uriFile.writeText(uri)
        }
        onStatus("Drive: gửi ${dir.name} (${zip.length() / 1_000_000}MB)…")
        if (!putResumable(tok, uri, zip, uriFile)) return false
        uriFile.delete(); zip.delete()
        File(dir, ".drive_uploaded").createNewFile()
        return true
    }

    /** Đã có file tên này trong folder JEPA chưa? (scope drive.file chỉ thấy file do app tự tạo —
     *  đủ cho dedup vì zip cũng do app này upload.) Lỗi mạng → coi như chưa có (sẽ thử upload). */
    private fun fileExists(tok: String, name: String, folderId: String): Boolean {
        val q = "name='${name.replace("'", "\\'")}' and '$folderId' in parents and trashed=false"
        val url = "https://www.googleapis.com/drive/v3/files?q=" +
            URLEncoder.encode(q, "UTF-8") + "&spaces=drive&fields=files(id)"
        return try {
            http.newCall(Request.Builder().url(url).header("Authorization", "Bearer $tok").build())
                .execute().use { r ->
                    if (!r.isSuccessful) return false
                    val files = JSONObject(r.body!!.string()).optJSONArray("files")
                    files != null && files.length() > 0
                }
        } catch (e: Exception) { false }
    }

    /** Tìm folder "JEPA", tạo nếu chưa có. null = lỗi (vd token hết hạn). */
    private fun ensureFolder(tok: String): String? {
        val q = "name='JEPA' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        val url = "https://www.googleapis.com/drive/v3/files?q=" +
            URLEncoder.encode(q, "UTF-8") + "&spaces=drive&fields=files(id)"
        http.newCall(Request.Builder().url(url).header("Authorization", "Bearer $tok").build())
            .execute().use { r ->
                if (!r.isSuccessful) return null
                val files = JSONObject(r.body!!.string()).optJSONArray("files")
                if (files != null && files.length() > 0) return files.getJSONObject(0).getString("id")
            }
        val meta = JSONObject().put("name", "JEPA").put("mimeType", "application/vnd.google-apps.folder")
        http.newCall(
            Request.Builder().url("https://www.googleapis.com/drive/v3/files?fields=id")
                .header("Authorization", "Bearer $tok")
                .post(meta.toString().toRequestBody("application/json".toMediaType())).build()
        ).execute().use { r ->
            if (!r.isSuccessful) return null
            return JSONObject(r.body!!.string()).getString("id")
        }
    }

    /** Khởi tạo resumable session → trả về URI để PUT nội dung. */
    private fun initResumable(tok: String, name: String, folderId: String): String? {
        val meta = JSONObject().put("name", name).put("parents", JSONArray().put(folderId))
        val req = Request.Builder()
            .url("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable")
            .header("Authorization", "Bearer $tok")
            .header("X-Upload-Content-Type", "application/zip")
            .post(meta.toString().toRequestBody("application/json; charset=UTF-8".toMediaType()))
            .build()
        http.newCall(req).execute().use { r -> return if (r.isSuccessful) r.header("Location") else null }
    }

    // PUT có RESUME: hỏi Drive đã nhận tới byte nào (PUT rỗng + Content-Range "bytes <star>/len"
    // → 308 kèm header Range "bytes=0-N") rồi chỉ gửi phần còn thiếu từ N+1. Session hết hạn
    // (404/410) → xoá URI đã lưu để lần retry sau init session mới.
    private fun putResumable(tok: String, uri: String, zip: File, uriFile: File): Boolean {
        val len = zip.length()
        var offset = 0L
        http.newCall(
            Request.Builder().url(uri).header("Authorization", "Bearer $tok")
                .put(ByteArray(0).toRequestBody(null))
                .header("Content-Range", "bytes */$len").build()
        ).execute().use { r ->
            when (r.code) {
                200, 201 -> return true                       // lần trước thật ra đã PUT xong
                308 -> offset = r.header("Range")             // "bytes=0-N"; null = chưa nhận byte nào
                    ?.substringAfter('-')?.toLongOrNull()?.plus(1) ?: 0L
                404, 410 -> { uriFile.delete(); return false }  // session hết hạn → init lại lần sau
                else -> return false
            }
        }
        if (offset > 0) {
            Log.i(TAG, "resume ${zip.name}: $offset/$len")
            onStatus("Drive: resume ${zip.name} (${offset * 100 / len}%)")
        }
        val body = object : okhttp3.RequestBody() {
            override fun contentType() = "application/zip".toMediaType()
            override fun contentLength() = len - offset
            override fun writeTo(sink: okio.BufferedSink) {
                java.io.FileInputStream(zip).use { fis ->
                    var left = offset
                    while (left > 0) { val sk = fis.skip(left); if (sk <= 0) break; left -= sk }
                    sink.writeAll(fis.source())
                }
            }
        }
        val req = Request.Builder().url(uri).header("Authorization", "Bearer $tok").put(body)
        if (offset > 0) req.header("Content-Range", "bytes $offset-${len - 1}/$len")
        http.newCall(req.build()).execute().use { r -> return r.isSuccessful }
    }
}
