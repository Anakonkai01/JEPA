package com.jepa.recorder

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import java.util.Locale

/** Danh sách session: mỗi dòng = tên + thống kê ngắn + cờ upload; nút ⋮ = menu thao tác. */
class SessionAdapter(
    private var items: List<SessionInfo>,
    private val onClick: (SessionInfo) -> Unit,
    private val onMenu: (SessionInfo, View) -> Unit,
) : RecyclerView.Adapter<SessionAdapter.VH>() {

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val info: TextView = v.findViewById(R.id.info)
        val menuBtn: Button = v.findViewById(R.id.menuBtn)
    }

    fun update(newItems: List<SessionInfo>) { items = newItems; notifyDataSetChanged() }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_session, parent, false))

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(h: VH, pos: Int) {
        val s = items[pos]
        val flag = if (s.driveUploaded) " ☁Drive" else if (s.uploaded) " ✓PC" else ""
        val lbl = if (s.label.isNotEmpty()) "  [${s.label}]" else ""
        h.info.text = String.format(Locale.US,
            "%s%s\n%d frame · %.0fs · steer μ%+.2f · ga μ%+.2f%s",
            s.name.removePrefix("session_"), lbl, s.frames, s.durationSec, s.steerMean, s.throtMean, flag)
        h.itemView.setOnClickListener { onClick(s) }
        h.menuBtn.setOnClickListener { onMenu(s, it) }
    }
}
