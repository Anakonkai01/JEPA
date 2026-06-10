package com.jepa.recorder

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.EditText
import android.widget.PopupMenu
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInClient
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.gms.common.api.ApiException
import com.google.android.gms.common.api.Scope
import com.jepa.recorder.databinding.ActivitySessionListBinding
import java.util.Locale

/** Màn quản lý session: liệt kê, xem lại (tap), và menu Thông tin / Nhãn / Xoá (+ Drive ở mục D). */
class SessionListActivity : AppCompatActivity() {

    private lateinit var ui: ActivitySessionListBinding
    private lateinit var adapter: SessionAdapter
    private lateinit var signInClient: GoogleSignInClient
    private lateinit var drive: DriveUploader
    private val driveScope = Scope("https://www.googleapis.com/auth/drive.file")

    private val signInLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { res ->
        try {
            val acc = GoogleSignIn.getSignedInAccountFromIntent(res.data).getResult(ApiException::class.java)
            drive.account = acc.account
            Toast.makeText(this, "Đã đăng nhập: ${acc.email}", Toast.LENGTH_SHORT).show()
        } catch (e: ApiException) {
            Toast.makeText(this, "Đăng nhập lỗi: ${e.statusCode}", Toast.LENGTH_LONG).show()
        }
        updateSignIn()
    }

    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        ui = ActivitySessionListBinding.inflate(layoutInflater)
        setContentView(ui.root)
        adapter = SessionAdapter(emptyList(), ::openPlayer, ::showMenu)
        ui.list.layoutManager = LinearLayoutManager(this)
        ui.list.adapter = adapter

        val gso = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestEmail().requestScopes(driveScope).build()
        signInClient = GoogleSignIn.getClient(this, gso)
        drive = DriveUploader(this) { st -> runOnUiThread { ui.status.text = st } }
        drive.start()
        GoogleSignIn.getLastSignedInAccount(this)?.let { drive.account = it.account }

        ui.signInBtn.setOnClickListener {
            if (drive.account == null) signInLauncher.launch(signInClient.signInIntent)
            else signInClient.signOut().addOnCompleteListener { drive.account = null; updateSignIn() }
        }
        ui.uploadAllBtn.setOnClickListener {
            if (drive.account == null) toast("Đăng nhập Google trước")
            else { drive.enqueuePending(SessionStore.root(this)); toast("Đã xếp hàng lên Drive") }
        }
        updateSignIn()
        reload()
    }

    private fun updateSignIn() {
        ui.signInBtn.text = if (drive.account != null) "Thoát GG" else "Đăng nhập"
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    override fun onResume() { super.onResume(); reload() }

    override fun onDestroy() {
        super.onDestroy()
        drive.stop()   // không stop → mỗi lần mở màn này leak 1 thread queue.take() vĩnh viễn
    }

    private fun reload() {
        Thread {
            val items = SessionStore.list(this)
            runOnUiThread {
                adapter.update(items)
                ui.empty.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
                ui.title.text = "Sessions (${items.size})"
            }
        }.start()
    }

    private fun openPlayer(s: SessionInfo) {
        startActivity(Intent(this, SessionPlayerActivity::class.java)
            .putExtra(SessionPlayerActivity.EXTRA_DIR, s.dir.absolutePath))
    }

    private fun showMenu(s: SessionInfo, anchor: View) {
        PopupMenu(this, anchor).apply {
            menu.add("Thông tin"); menu.add("Đổi tên / Nhãn"); menu.add("⬆ Drive"); menu.add("Xoá")
            setOnMenuItemClickListener { mi ->
                when (mi.title) {
                    "Thông tin" -> showInfo(s)
                    "Đổi tên / Nhãn" -> showLabel(s)
                    "⬆ Drive" -> if (drive.account == null) toast("Đăng nhập Google trước") else {
                        drive.enqueue(s.dir); toast("Đã xếp ${s.name} lên Drive")
                    }
                    "Xoá" -> confirmDelete(s)
                }
                true
            }
            show()
        }
    }

    private fun showInfo(s: SessionInfo) {
        val msg = String.format(Locale.US,
            "Tên: %s\nFrame: %d\nThời lượng: %.1fs (~%.1f fps)\n" +
                "Steer: μ%+.3f σ%.3f\nThrottle: μ%+.3f σ%.3f\nδ_cam tb: %.1f ms\n" +
                "Tailscale: %s · Drive: %s\nNhãn: %s",
            s.name, s.frames, s.durationSec,
            if (s.durationSec > 0) s.frames / s.durationSec else 0.0,
            s.steerMean, s.steerStd, s.throtMean, s.throtStd, s.dcamMeanMs,
            if (s.uploaded) "đã gửi" else "chưa", if (s.driveUploaded) "đã gửi" else "chưa",
            if (s.label.isEmpty()) "(không)" else s.label)
        AlertDialog.Builder(this).setTitle("Thông tin").setMessage(msg)
            .setPositiveButton("OK", null).show()
    }

    private fun showLabel(s: SessionInfo) {
        val et = EditText(this).apply { setText(s.label); hint = "vd: good / recover / cong-vien" }
        AlertDialog.Builder(this).setTitle("Nhãn / ghi chú").setView(et)
            .setPositiveButton("Lưu") { _, _ ->
                SessionStore.setLabel(s.dir, et.text.toString().trim()); reload()
            }.setNegativeButton("Huỷ", null).show()
    }

    private fun confirmDelete(s: SessionInfo) {
        AlertDialog.Builder(this).setTitle("Xoá session?")
            .setMessage("${s.name}\n${s.frames} frame — không khôi phục được.")
            .setPositiveButton("Xoá") { _, _ ->
                Thread {
                    val ok = SessionStore.delete(s.dir)
                    runOnUiThread {
                        Toast.makeText(this, if (ok) "Đã xoá" else "Xoá lỗi", Toast.LENGTH_SHORT).show()
                        reload()
                    }
                }.start()
            }.setNegativeButton("Huỷ", null).show()
    }
}
