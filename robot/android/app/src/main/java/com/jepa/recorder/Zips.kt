package com.jepa.recorder

import java.io.BufferedOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Nén 1 thư mục session thành .zip (đường dẫn entry tương đối) — dùng chung cho Uploader + DriveUploader. */
object Zips {
    fun zipDir(dir: File, zipFile: File) {
        ZipOutputStream(BufferedOutputStream(zipFile.outputStream())).use { zos ->
            dir.walkTopDown().filter { it.isFile }.forEach { f ->
                // entry.time = mtime file (mặc định = "bây giờ") → zip DETERMINISTIC giữa các lần
                // nén lại — bắt buộc cho Drive resume byte-offset (phần đã gửi phải khớp bit-bit).
                zos.putNextEntry(ZipEntry(f.relativeTo(dir).path).apply { time = f.lastModified() })
                f.inputStream().use { it.copyTo(zos) }
                zos.closeEntry()
            }
        }
    }
}
