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
                zos.putNextEntry(ZipEntry(f.relativeTo(dir).path))
                f.inputStream().use { it.copyTo(zos) }
                zos.closeEntry()
            }
        }
    }
}
