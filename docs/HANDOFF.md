# HANDOFF — đọc cái này trước khi tiếp tục

> Tóm tắt tình hình cho phiên sau. Cập nhật: **2026-06-12**.
> Nền đầy đủ: [../CLAUDE.md](../CLAUDE.md) · [../README.md](../README.md) · [PLAN.md](PLAN.md) ·
> [LeWorldModel.md](LeWorldModel.md) · [../robot/android/README.md](../robot/android/README.md) ·
> [../robot/android/DRIVE_SETUP.md](../robot/android/DRIVE_SETUP.md). Cập nhật file này mỗi khi trạng thái đổi.

## 🏆 2026-06-12 TỐI (đợt 2) — POP FIX ×2 (LATCH + GEO-CONFIRM) → **XE LẦN ĐẦU TỰ QUA CUA** (user xác nhận, nhiều run liên tiếp)

> Tiếp buổi tối ở park. User phát hiện đúng chỗ chết: **xe ĐÃ đi qua subgoal, cos ĐÃ từng vượt ngưỡng,
> mà KHÔNG pop → kẹt ghim subgoal cũ mãi**. Soi code + log bắt được 2 bug pop, fix tại trận, và sau fix
> **user chạy 3-4 run liên tiếp: "fix ổn nhất từ trước tới giờ, model đã THẬT SỰ cua được, hơi lệch
> nhưng rất oke, rất hài lòng"** — nhớ ĐÍNH CHÍNH 06-12: trước hôm nay cua CHƯA BAO GIỜ qua được
> bằng bất kỳ cách nào → **đây là bước tiến quan trọng nhất của control tới giờ.**

**★ BUG 1 — POP LỆCH PHA (latch, `inference_loop.py` nhánh pop GPS route tay):** 3 điều kiện pop bị
AND tại CÙNG 1 tick nhưng chúng đúng ở 2 THỜI ĐIỂM khác nhau: `ccos ≥ pop-confirm-cos` ĐỈNH lúc xe
Ở/tiến tới subgoal (lúc đó "đã đi qua" = subgoal-kế-gần-hơn CHƯA đúng → break), còn "đã đi qua" chỉ
đúng SAU khi qua (lúc đó camera đã nhìn cảnh phía sau → ccos TỤT dưới ngưỡng → veto ảnh chặn). Tệ
nhất: vòng pop chỉ chạy khi `d < reach-m` → xe đi tiếp là **cửa sổ pop ĐÓNG VĨNH VIỄN** (log 16:04
park1: ghim `manual 1/30`, d 1.2→20m). **Fix: `man_seen` LATCH "ảnh đã khớp" ở bất kỳ tick nào →
pop lúc đi qua dù ccos hiện tại đã tụt; đã latch thì bỏ luôn cổng reach-m.** Verify chạy thật
parkfix2: subgoal 1-6 pop chuẩn (`GPS qua + ảnh ĐÃ khớp`), pop tại d 0.2-1.2m, tuần tự không nhảy cóc.

**★ BUG 2 — VETO ẢNH Ở CUA (geo-confirm):** sau latch, sg7 vẫn kẹt: xe **ĐÈ LÊN mốc d=0.1m**, GPS
xác nhận đã qua, mà ccos đỉnh chỉ **0.48 < 0.5** → không bao giờ latch → timeout 60s. Cơ chế ĐO ĐƯỢC
(chuỗi ccos lúc pop GIẢM DẦN khi vào cua: sg4 0.737 → sg5 0.668 → sg6 0.528 → sg7 0.48): **ở cua,
heading lúc repeat lệch heading lúc teach → cùng xy mà view khác → ảnh bản chất KHÔNG khớp nổi** —
hạ ngưỡng là đuổi vô tận (sg khác lại hụt kiểu khác). **Fix: GPS sát < min(1.5m, reach-m) (noise
median 0.44m) cũng tính là XÁC NHẬN** — confirm ảnh để chống pop-bừa-TỪ-XA, không phải quyền phủ
quyết khi xe đã đè lên mốc. Log pop giờ ghi rõ cách xác nhận: `(GPS qua + ảnh khớp ccos x)` /
`(GPS qua + tới sát x.xm)`. Lưu ý kèm: route teach cũ KHÁC ánh sáng (park1 teach trưa chạy 16h) thì
ccos ≈ 0 ngay TẠI mốc — geo-confirm cứu được pop, nhưng control vẫn cần route teach mới/cùng-giờ.

**★ KẾT QUẢ + CONFIG USER CHỐT TẠI TRẬN (đã ghi trong `run_infer.sh`, user tự chỉnh KHÁC đề xuất):**
`--samples 256 --iters 2` (tick chậm đổi lấy search dày — user chấp), ga `--throttle-cap 0.10
--cruise-throttle 0.10 --kick-throttle 0`, `--lock-cos 0.10 --lock-hold-s 10` (HOLD gần như tắt —
ít can thiệp), `--pop-confirm-cos 0.5 --reach-m 6 --ctrl-lookahead-m 0.5 --heading-cap-deg 35
--steer-smooth 0.1 --turn-slow 0 --no-recover`. Route `parkfix2` (0.4m, 31 subgoal). Kết quả: **qua
cua nhiều run liên tiếp, còn "hơi lệch" (lateral offset) nhưng bám được route.**

**★ VẬN HÀNH MỚI:** `run_infer.sh` giờ **TỰ GHI LOG** mỗi run → `logs/infer_<ngày_giờ>.log` (tee,
vẫn in màn hình; `logs/` đã vào .gitignore). Lý do: 3-4 run ĐẸP NHẤT hôm nay chạy terminal trần →
**không còn log per-tick để phân tích** — từ mai mọi run đều có vết.

**🔜 VIỆC NGÀY MAI (user chốt: test tiếp + đánh giá phân tích + cập nhật lưu trữ):** (1) số liệu hoá
"hơi lệch" — lateral offset so polyline teach từ GPS trong log run; (2) đo tỉ lệ qua-cua / pop đúng
trên N run; (3) thử lại 32/1 vs 256/2 (lệch có phải do tick chậm? HANDOFF cũ đo offline 32/1 ngang
64/2 — 256/2 chưa từng đo); (4) quay video + số liệu báo cáo. Câu hỏi mở cũ "model có ĐỦ KHẢ NĂNG
qua cua không" → **ĐÃ TRẢ LỜI: CÓ** (khi target/pop đúng); phương án pure-pursuit/GPS-heading dự
phòng KHÔNG cần nữa trừ khi "hơi lệch" không trị được.

## 🌃 2026-06-12 TỐI/ĐÊM — PARK CHẠY THẬT: 3 FIX CUA trên inference_loop + ĐO ĐƯỢC "model BIẾT lái cua" (KHÔNG đi indoor — fix cua ngoài park)

> Tiếp buổi chiều. User KHÔNG đi indoor nữa — ở lại park chạy thật teach&repeat LIVE (`teach_record.py`),
> Claude theo dõi log + sửa code tại trận qua nhiều run. **KẾT LUẬN LỚN: model KHÔNG dốt cua** — đo được
> offline + thấy nó ra `steer +1.0` đúng phía khi chạy thật. **Mọi thất bại cua = TARGET-SELECTION / POP /
> GA-FULL-LOCK / SMOOTHING, không phải năng lực model.** Đã sửa 3 chỗ code + viết bộ script chạy; route
> dày chạy tới subgoal 13/31. **Fix cuối CHƯA verify trọn vòng** (xem CÒN MỞ).

**★ ĐO ĐƯỢC (probe_energy, cd4, offline in-domain park) — model lái cua TỐT:**
- `python scripts/probe_energy.py --turn-only -d 4 --n-windows 60`: argminE **đúng hướng quẹo 58/60**,
  median |argminE−teacher| 0.12, **contrast 0.37**. → energy có đáy đúng phía ở cua.
- Contrast TỤT theo khoảng cách target (mất overlap): **d2 0.443 / d4 0.355 / d8 0.270**. → "mất target khi
  target xa/quanh-góc" là cơ chế ĐO ĐƯỢC. Trị bằng TARGET GẦN + teach DÀY, không phải train.

**★ 3 FIX CODE trong `scripts/inference_loop.py` (compile OK, CHƯA commit — xem git status):**
1. **Lookahead heading-aware cho NHÁNH ROUTE-TAY** (port từ graph): dựng polyline arc-length + heading
   central-diff từ xy TEACH các subgoal; control-target = subgoal cách `--ctrl-lookahead-m` along-track từ
   wp_idx, **DỪNG SỚM khi heading xoay ≥ `--heading-cap-deg`** (flag MỚI, default 50, áp CẢ graph). Control
   **GPS-độc-lập** (dùng xy teach + cos; GPS live chỉ là cổng thô — trả lời "GPS có cải thiện được không":
   KHÔNG cần, đã đưa GPS ra khỏi vòng lái).
2. **POP-FIX chống "GPS nuốt subgoal"**: pop GPS route tay giờ CHỈ pop khi xe đã ĐI QUA subgoal (subgoal kế
   gần hơn). Trước: route dày ~1m << reach 6m → startup nuốt 4 subgoal/1 tick khi xe đứng yên → wp_idx nhảy
   trước xe → target ra ngoài overlap → rail lái + kẹt + lùi-tựa-lửa. (Cũng hạ `--reach-m` 6→2.5.)
3. **"GIỮ LÁI XUYÊN VÙNG MÙ" (commit-through-turn)**: flag MỚI `--lock-cos` (0.30), `--lock-hold-s` (4.0).
   cos→control-target tụt < lock-cos giữa cua (CEM hết gradient → ra noise ±1 → xe chệch khỏi) → ĐÓNG BĂNG
   lái ở cú quẹo cuối **CHỈ khi |steer|>0.25 (quẹo thật)**; cos hồi → CEM tiếp; giữ > lock-hold-s chưa hồi →
   DỪNG neutral (hết veer đi 12m). Log thêm tag `HOLD±x.xx`. ⚠️ Bug đã gặp+sửa: nếu lookahead XA, CEM ra ~0
   ở cua → HOLD đóng băng THẲNG (`HOLD+0.00`) → đâm; nên lookahead phải NGẮN (0.5) + HOLD chỉ giữ quẹo thật.

**★ SCRIPT CHẠY (repo root, MỚI — tránh lỗi đứt-dòng khi paste; user TỰ chạy, xem [[live-robot-user-drives]]):**
`bash run_web.sh` · `bash run_infer.sh` (sửa số TRONG file) · `bash run_teach.sh <tên>` (teach_record --step-m 0.4).

**★ BÀI HỌC CHẠY THẬT (đo tại trận):**
- **GA full-lock**: 0.07 KHÔNG lăn (ma sát tĩnh sàn), 0.14 VỌT giật. **`--turn-slow` MẶC ĐỊNH cắt ~nửa ga ở
  |steer|=1 → full-lock SCRUB KẸT** (ga tụt còn 0.03). Fix: **`--turn-slow 0`** + cruise ~0.10-0.12 (sàn hằng,
  vô điều kiện) để có lực scrub qua cua. kick 0 + cruise hằng = đề-pa ÊM (không giật như kick).
- **steer-smooth**: 0.6 (mặc định) Ì → **bóp nửa lực quẹo → ĐI THẲNG** (model ra raw ±1.0 mà áp chỉ ±0.5,
  bằng chứng rõ trong log). Dùng **0.1** (quẹo được) → 0.2-0.3 nếu twitchy.
- **TEACH DÀY ĂN RÕ**: `parkfix1` (0.8m, 33 sub) chết ở subgoal 2-3; **`parkfix2` (0.4m, 31 sub) chạy tới
  subgoal 13** (qua nhiều cua, cos dip rồi TỰ HỒI). Cua gắt → teach 0.4m, đi CHẬM + cung RỘNG MƯỢT (đừng pivot).
- **LOOKAHEAD ở cua phải NGẮN (0.5)**: lookahead 1.0 (→la = wp+2) ngắm subgoal quanh-góc (out-of-overlap) →
  CEM ra ~0 (thẳng) → HOLD đóng băng thẳng → "không quẹo, đi thẳng rồi chết". 0.5 (→la = wp+1) gần, đòi quẹo, còn overlap.

**★ CONFIG TỐT NHẤT hiện tại (đã ghi sẵn trong `run_infer.sh`):** `--reach-m 2.5 --no-recover --samples 32
--iters 1 --ctrl-lookahead-m 0.5 --heading-cap-deg 35 --pop-confirm-cos 0.5 --steer-smooth 0.1 --turn-slow 0
--throttle-cap 0.09 --cruise-throttle 0.09 --kick-throttle 0.0 --lock-cos 0.30 --lock-hold-s 4.0`. Route chạy:
`data/routes/manual/parkfix2` (dày 0.4m, 31 subgoal). Checkpoint vẫn cd4 best.pt + policy_prior.

**🔴 CÒN MỞ (✅ ĐÃ GIẢI QUYẾT đợt 2 — xem section 🏆 trên: thủ phạm thật là POP, fix latch+geo-confirm, xe ĐÃ qua cua):** Fix cuối (lookahead 1.0→0.5 + HOLD-chỉ-giữ-|steer|>0.25)
**CHƯA chạy thử lại** (sửa xong là hết phiên). Session sau: chạy 3 script + ▶ Run `parkfix2`, soi 2 cua gắt
**subgoal 6 và 14**:
- CEM có ra **cú QUẸO** (`steer+0.x` tới target gần) ở cua không? Tag `HOLD+0.85` (giữ QUẸO) chứ không `HOLD+0.00`?
- **CÓ qua được cua** → fix cua XONG → chạy trọn vòng + quay video làm số liệu báo cáo.
- **CEM VẪN ra thẳng ở cua dù target gần** → model không quyết quẹo cho subgoal đó (khác HOLD) → soi `--step`
  ngay tại cua, hoặc làm **lái hình học (pure-pursuit theo route heading)** — cần car-heading (GPS-track lúc
  lăn / rotvec phone). Đây là phương án SÂU nếu visual-servo không đủ cho cua gắt.

## 🏞️ 2026-06-12 CHIỀU — PARK teach&repeat LIVE-RECORD: ĐOẠN THẲNG NGON, CUA GẮT VỠ (cấu trúc) → USER CHỐT PIVOT INDOOR

> Tiếp buổi sáng. Bỏ teach-tay-đứng-chụp (dày, cos loạn). **Ý user (HAY): tự lái 1 vòng quay live →
> session đó thành route → đem xe về đầu + chạy lại.** Đã build công cụ + chạy thật. Kết: **đoạn thẳng
> chạy NGON, cua gắt VỠ LẶP LẠI**. User chốt: **về nhà, thu data INDOOR, cooldown train domain-adapt,
> test+fix trong nhà (dễ iterate), BẮT BUỘC fix được CUA — chỉ đi thẳng = vứt.** Mọi process field đã
> tắt, GPU free, cd4 vẫn là ckpt tốt nhất.

**⚠️ ĐÍNH CHÍNH QUAN TRỌNG (user, 06-12 tối): CUA CHƯA BAO GIỜ CHẠY ĐƯỢC — chưa 1 lần, bằng BẤT KỲ
cách nào (graph route LẪN route tay).** Mọi chỗ section cũ ghi "KỶ LỤC 40m tự đi" là TÔ HỒNG: 40m đó
đâm lề/đâm bụi LIÊN TỤC, user phải chỉnh tay; KHÔNG navigate sạch 1 khúc cua nào. → **Lookahead
heading-aware KHÔNG phải fix đã chứng minh** (graph route CÓ code đó mà vẫn không qua cua) — coi là
GIẢ THUYẾT-CẦN-ĐO. **Câu hỏi cốt lõi chưa ai đo: model có ĐỦ KHẢ NĂNG đánh lái đúng qua 1 cua không?**
(offline `probe_energy` chỉ test ảnh-đích SÁT mặt = dễ; ở cua online = chưa đo bao giờ.) → **ĐO TRƯỚC
bằng `--step`** (mục FIX CUA) rồi mới chọn hướng, đừng vặn nút theo giả định.

**★ CÔNG CỤ MỚI `scripts/teach_record.py` (teach&repeat đúng nghĩa, KHÔNG cần REC/upload):**
PC đang nhận sẵn luồng live của phone → script đọc `live_status.json` (car_xy do inference idle ghi) +
gọi `POST /api/manual/snap` MỖI khi xe đi `--step-m` mét → dựng route tay DÀY từ chính luồng live
(cùng tiền-xử-lý + cùng ánh sáng hôm nay = **zero domain-shift**, heading lái-tiến thật). Flow:
1. `route_web.py` + `inference_loop.py --web` (graph mode, idle stream — KHÔNG cần graph cho việc teach,
   chỉ cần car_xy từ GPS). 2. CH9≠AUTO, lái 1 vòng remote. 3. `python scripts/teach_record.py <tên>
   --step-m 1.0` (chạy nền) → snap mỗi ~1m. 4. Stop script (SIGTERM tự `POST /api/routes` lưu descriptor)
   → route hiện web list. 5. Đem xe VỀ frame 000 + ĐÚNG HƯỚNG teach → CH9 AUTO → ▶ Run. Đã tạo
   `data/routes/manual/park1` (30 subgoal, ~38m loop). **HƯỚNG đặt xe lúc Run = tối quan trọng** (lệch
   hướng → cos âm → ghim lái).

**KẾT QUẢ ĐO ĐƯỢC:**
- **ĐOẠN THẲNG (subgoal 1–5): CHẠY NGON** — cos centered DƯƠNG 0.5–0.86, lái nhẹ đúng hướng, advance
  mượt. **Live-record teach + cùng ánh sáng = đã chữa lỗi cos-âm/ghim-trái của teach-tay-đứng-chụp.**
- **CUA GẮT (subgoal 6, quẹo phải): VỠ LẶP LẠI 2 LẦN** — user: "phải quẹo phải mà nó quẹo TRÁI rồi
  đâm thẳng bụi cỏ". Log: target = subgoal QUANH GÓC xe CHƯA nhìn thấy → **centered-cos ÂM (−0.22)** →
  world-model không có overlap → CEM chọn **full-TRÁI nhất quán (raw −1.0 mọi tick, KHÔNG phải noise)**
  → d phình 2.4→5.1m → lạc khỏi route vào bụi. **Đây là ĐIỂM YẾU CẤU TRÚC của route-tay, KHÔNG phải
  OOD/tuning**: route-tay chỉ ngắm subgoal GPS-gần-nhất; ở cua target nằm NGOÀI overlap → energy bừa → lái bừa.
  (Route-tay thiếu lookahead heading-aware mà graph route có — NHƯNG xem ĐÍNH CHÍNH: graph route có nó
  mà CŨNG không qua cua, nên thiếu-lookahead không phải nguyên nhân duy nhất / đủ.)

**CÁC FIX/BÀI HỌC GA+POP (cho lần manual repeat sau):**
- **Continuous >> pulse outdoor** (tái khẳng định 06-11): pulse mỗi nhịp xuất phát từ đứng yên → phải
  phá ma sát tĩnh → bò 0.1 m/s → stuck-detector báo nhầm → recovery → halt. Liên tục giữ trớn mới đi được.
- **⚠️ `--kick-throttle`/`--cruise-throttle` GHI ĐÈ `--throttle-cap`** (là floor `max()`, KHÔNG bị
  clamp lại về cap). Đặt kick 0.16 → vì xe chậm `spd_est < stuck_speed 0.15` nên **kick bắn MỌI tick →
  ga GHIM 0.16 = MAX, giật khủng khiếp** (user phàn nàn). **LUẬT: kick ≤ cap và cruise ≤ cap.** Để giới
  hạn CỨNG 0.07–0.08: `--throttle-cap 0.08 --cruise-throttle 0.07 --kick-throttle 0.07` (không gì vượt 0.08).
- **`--reach-m` (route dày 1m, `--pop-confirm-cos 0` outdoor): đánh đổi khoảng-cách-target.** 1.5 quá
  CHẶT (xe tới 1.6m, hụt pop trong gang → target dí sát đầu → energy phẳng → CEM lái RANDOM ±1.0 → lạc).
  2.5 quá XA (target ~3.5m quanh cua → cos thấp → lái +0.8 → scrub đứng im). ~2.0 ở giữa. Gốc: discrete-
  subgoal không có target liên tục → quá gần=phẳng, quá xa=mất overlap. **Lookahead (dưới) mới là lời giải.**
- **`--turn-slow 0`** chống scrub (giữ ga trong cua) NHƯNG bỏ luôn phanh-trong-cua → xe quay sai vào bụi
  mà ga vẫn 0.08 ("vào bụi cỏ còn tăng ga"). ĐỪNG dùng 0; dùng ~0.3 (chậm trong cua mà không stall).

**🔧 FIX CUA (việc must-win, làm trong nhà): THÊM LOOKAHEAD HEADING-AWARE VÀO NHÁNH ROUTE-TAY** của
`inference_loop.py` (port từ nhánh graph ~L893–933): dựng polyline xy từ các subgoal tay → chiếu xe lên
(monotonic, chỉ-tiến) → target = subgoal cách ~`--ctrl-lookahead-m` ALONG-TRACK nhưng **DỪNG SỚM nếu
heading route xoay ≥~50°** → target luôn nằm trong overlap, vào cua tự dày. Ngắm ẢNH subgoal đó qua
`manual_patch`. ⚠️ **KHÔNG phải fix đã chứng minh** (xem ĐÍNH CHÍNH — 40m KHÔNG sạch). **ĐO TRƯỚC bằng
`--step`**: dựng 1 CUA ĐƠN trong nhà → đi từng nhịp, in `E(steer)` 5 nấc → xem ở GIỮA cua model có BAO
GIỜ chỉ đúng hướng không. CÓ → target/pop sai, lookahead/target-gần có cửa. KHÔNG → lỗi MODEL (cần
train/domain-adapt, hoặc cách servo-1-ảnh không làm được cua → đổi chiến lược). (Hiện route-tay ngắm
`subs[wp_idx]` thuần GPS.)

**KẾ HOẠCH USER CHỐT (pivot indoor — thứ tự làm):**
1. **Thu data INDOOR**: lái FlySky REC (CH10) trong nhà ~30–60' → `sync_dataset` + `encode_patch` 384
   → root mới `data/latents_indoor_patch_384` (domain_id=1 towerpro) → cooldown từ cd4-best 1–2 ep
   (~3–6h) + retrain `policy_prior` (~20'). (Chi tiết: section 06-12 SÁNG §6.)
2. **Test + fix trong nhà** (dễ iterate nhất: gần, lặp nhanh, đủ sáng). Dùng `teach_record.py` teach
   route trong nhà (có GPS rác trong nhà → cân nhắc `--graph none` + pop bằng cosine, HOẶC teach ngoài
   sân gần nhà). **Indoor data chữa OOD; CUA là lỗi RIÊNG (cấu trúc) → vẫn phải thêm lookahead (trên).**
3. **Lệnh manual repeat sau khi có lookahead**: `--throttle-cap 0.08 --cruise-throttle 0.07
   --kick-throttle 0.07 --turn-slow 0.3 --no-recover --steer-smooth 0.4 --reach-m 2.0
   --ctrl-lookahead-m <~1.5> --samples 32 --iters 1 --policy <prior>` (+ checkpoint indoor-cooldown khi xong).

## 🏞️ 2026-06-12 TRƯA — CHẠY THẬT PARK (in-domain, teach&repeat route tay "ngoaiduong") — 4 fix tại trận, 1 vấn đề CÒN MỞ

> Buổi sáng park, đúng điều kiện in-domain. User teach route tay 10 subgoal + Run; Claude theo dõi log debug.
> **TRẠNG THÁI KHI DỪNG (sắp hết context): inference forward-only + route_web ĐANG CHẠY** (PID
> 1744619 + 1740130). Logs: `logs/infer_fwd.log` (inference), `logs/route_web_run.log`. PC Tailscale
> 100.110.165.40:8060; phone 100.64.68.96 stream OK; GPU rảnh trước đó (cd8 paused), cd4 ckpt.

**LỆNH ĐANG CHẠY (forward-only, pulse) — relaunch session sau = đúng lệnh này:**
```bash
PYTHONPATH=src python scripts/route_web.py            # web :8060 (graph default, outdoor có GPS)
PYTHONPATH=src python scripts/inference_loop.py --web --reach-m 6 --stuck-s 3 \
  --samples 64 --iters 2 --steer-smooth 0 \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --throttle-cap 0.08 --pulse --pulse-move 0.45 --settle-s 0.8 --pop-confirm-cos 0.5
```

**1. BUG DOC: lệnh park cũ `--throttle-cap 0.065` + cruise mặc định 0.07 → cruise>cap → ga GHIM 0.07,
model mất quyền ga** (cảnh báo startup bắt được). Run KỶ LỤC 40m thực ra dùng **cap mặc định 0.08**
(cruise 0.07 < 0.08). → bỏ `--throttle-cap 0.065`, dùng 0.08.

**2. ✅ FIX "GPS NUỐT SUBGOAL" = `--pop-confirm-cos 0.5` (CHẠY ĐÚNG):** route tay teach DÀY (subgoal
cách 0.3–3m) << reach-m 6 → vòng `while` pop (inference_loop.py ~L719) pop HẾT subgoal trong 6m
một tick → nhảy thẳng subgoal xa 8.6m (cos âm = hết overlap) → CEM mù → lái ghim trái → recovery →
🛑 KẸT. Bật pop-confirm-cos → GPS chưa đủ, ẢNH phải khớp (centered-cos ≥ ngưỡng) mới pop → **tuần tự,
không nhảy cóc** (log: subgoal1 ccos 0.878 → subgoal2 0.552 → subgoal3 giữ vì 0.171<0.5). HANDOFF
luôn cảnh báo: ĐỪNG teach subgoal dày < GPS noise ±2m.

**3. ✅ FIX "cứ lùi lùi, đứng 1 chỗ đánh lái": TẮT lùi (`--throttle-min 0`, forward-only):** user xin
ga lùi 0.09 → tôi đặt `--throttle-min=-0.09` + bỏ policy → ở subgoal cos thấp (energy PHẲNG) CEM vớ
"lùi" trong nhiễu MỌI nhịp (`ga model -0.090`) → xe lùi miết không bao giờ tới subgoal. Đây đúng lý do
config 40m CẤM lùi ("no surprise reverse"); lùi thật chỉ để stuck-recovery. → bỏ throttle-min (=0).
⚠️ **argparse gotcha: `--throttle-min -0.09` CRASH** (đọc -0.09 thành flag, exit 1 không traceback) →
phải `--throttle-min=-0.09` nếu cần.

**4. Yêu cầu user "dừng-hết quán tính-chụp-rồi quyết định" = `--pulse --settle-s 0.8`** (đi 1 nhịp
0.45s → ngắt ga → chờ 0.8s hết trớn → lấy frame → quyết định) + bỏ policy + steer-smooth 0 (quyết
định tươi, không bias lái) + samples 64/iters 2 (pulse chậm không ngại trễ). tick ~1.5s (cem 1.49).

**🔴 VẤN ĐỀ CÒN MỞ (làm trước session sau):** route tay "ngoaiduong" teach **QUÁ DÀY** → subgoal 3
(`data/routes/manual/ngoaiduong/002.jpg`) **cos max ~0.29, không bao giờ chạm 0.5 → không pop → 60s
timeout → DỪNG**. centered-cos không phân biệt sạch subgoal sát nhau (0.878/0.552/0.29 nhảy loạn).
2 đường: (a) **HẠ `--pop-confirm-cos` xuống ~0.3** (rủi ro nuốt lại ở chỗ subgoal kề cos cao); (b)
**TEACH LẠI route THƯA hơn** (~4–5m/subgoal, chỉ DÀY ở cua gắt, view khác biệt rõ — đúng spacing
graph-route đã chứng minh 40m). Khuyến nghị (b). Chưa kịp thử forward-only có để xe tới được subgoal 3
không (lần chạy lùi nó lùi xa nên cos không lên) — session sau Run lại lệnh đang chạy, xem cos có lên
khi xe BÒ TIẾN tới subgoal không; nếu vẫn kẹt → re-teach.

**Bài học vận hành:** dùng `run_in_background` (KHÔNG `&` — SIGHUP giết); pgrep lọc `grep -v "/bin/bash -c"`
gây tưởng-nhầm process chết (thực ra sống) → kiểm tra bằng `ps -eo pid,etime,args | grep inference_loop`.
Kill bằng `pkill -9 -f scripts/inference_loop.py` (không đụng route_web). Mỗi lần đổi flag = relaunch
(~30s load model) + phone tự reconnect + user bấm ▶ Run lại trên web.

## 🔍 2026-06-12 SÁNG — AUDIT INFERENCE: "cosine lúc nào cũng cao" = ĐO ĐƯỢC + FIX (centered cos); indoor NGU = OOD ĐO ĐƯỢC; cd8 PAUSE @ ep0

**User báo 8 nghi vấn (indoor chạy "ngu ngu": cosine cao đều, lái lệch/không quẹo, không lùi,
nghi quán tính/trễ, nghi cap/floor đè model, nghi history, reach-check vs Meta) → audit + đo + fix:**

**1. "COSINE NÀO CŨNG CAO" — đúng, đo được, ĐÃ FIX bằng CENTERED COSINE (`scripts/probe_reach.py` MỚI):**
cos pooled THÔ trên 2 route indoor (test_nha 10 ảnh / test_nha_2 8 ảnh): ảnh-kề 0.982/0.985,
xa-nhau-nhất vẫn 0.940/0.953 → dải động ~0.04, ngưỡng 0.97/0.999 đều vô nghĩa (pooled V-JEPA có
thành-phần-chung khổng lồ "đây là ảnh trong nhà"). **Fix: TRỪ MEAN pooled các subgoal route rồi mới
cos** → kề ~+0.5 / cách-2 ~0.0 / xa ~−0.4, nearest-neighbor đúng 10/10 + 7/8. Đã vào
`inference_loop.py` route tay (route ≥2 ảnh tự dùng centered; 1 ảnh rơi về cos thô): **defaults MỚI
`--manual-reach-cos 0.80 / --manual-near-cos 0.40`, margin luật-tương-đối 0.10** — ⚠️ ĐỪNG truyền
ngưỡng thang cũ (0.97/0.999) nữa. E2E fake-phone pass: nhìn SAI chỗ cos −0.74/−0.48, đúng chỗ 1.000,
pop 3/3 + 🏁. (L1 patch-token cũng probe: tách được nhưng kém ccos; energy CEM giữ nguyên L1.)

**2. INDOOR "LÁI NGU/LỆCH PHẢI KHI CẦN QUẸO TRÁI" = MODEL OOD — ĐO ĐƯỢC, không phải config:**
`probe_energy --frames-dir` trên 2 route nhà (log `logs/probe_indoor_*.log`, chạy 02:11):
**median contrast 0.045/0.056 vs park ban ngày 0.39 (≈8× phẳng hơn)**, argminE đổi dấu loạn xạ
giữa các ảnh kề nhau → landscape energy indoor GẦN PHẲNG, CEM bám noise; policy prior cũng BC từ
park. Tăng samples/iters KHÔNG cứu (A2 đã đo @32/1+policy ≈ @64/2+policy); steering box vốn
KHÔNG cap ([-1,1] full). → Indoor muốn chính xác = **THU DATA INDOOR** (xem mục 6).

**3. NGHI "CAP/FLOOR ĐÈ MODEL" — đúng MỘT NỬA, 2 bug thật đã fix:**
- **Lệnh user đang chạy có `--cruise-throttle 0.07 > --throttle-cap 0.05` → sàn ĐÈ trần: ga hằng
  0.07 MỌI tick, model mất 100% quyền ga** (đâm thẳng không hãm ở cua là phải). Giờ startup in
  ⚠️ cảnh báo; indoor đúng là cap 0.05 / cruise 0.04.
- **Floor đè turn_slow** (đã ghi nhận 06-11, nay fix): floor giờ TURN-AWARE
  `floor = cruise·max(0.6, 1−turn_slow·|steer|)` → vào cua sàn ga tự giảm (chặn dưới 0.6× để còn lăn);
  kick giữ nguyên lực (đề-pa). Steering KHÔNG bị cap ở đâu cả (EMA user đã tắt =0).

**4. "SAO KHÔNG TỰ LÙI" → `--throttle-min` MỚI (default 0 = như cũ):** đặt âm (vd −0.11) cho CEM
box ga = [min, cap] → **model tự chọn lùi** (thay lùi-mù hardcode); floors/kick tự đứng ngoài khi
model ra ga âm. Lưu ý kickstart policy lúc đứng-yên vẫn ép mu tiến → lùi chủ yếu khả thi khi đang lăn.

**5. NGHI "QUÁN TÍNH/TRỄ — frame cũ lúc ra quyết định xe đã dịch" — ĐÚNG hiện tượng, định lượng:**
tuổi frame lúc action chạm bánh ≈ δ_cam 0.10 + uplink ~0.05-0.1 + encode 0.03 + CEM 0.33 ≈ **0.5s**;
CEM nhìn 4×0.22 = 0.88s tương lai, action đầu bị giữ ~0.4s (1 tick). Đi 0.5 m/s → lệch ~0.25m so
với frame — khớp quan sát "chạy cực chậm thì ổn hơn hẳn". Thuốc có sẵn: **`--pulse`** (chạy 1 nhịp
→ NGẮT GA trong lúc tính → frame plan gần tĩnh) — indoor ưu tiên chính xác NÊN BẬT;
và **`--step` MỚI** = pulse bấm tay để debug (mục 7).

**6. "TRAIN TIẾP DOMAIN TRONG NHÀ?" — khả thi, đây là fix THẬT cho indoor:** lái FlySky thu
~30-60' session TRONG NHÀ (CH10 REC như cũ) → `sync_dataset` + `encode_patch` 384 → thêm root
`data/latents_indoor_patch_384` (servo TowerPro → domain_id=1 như cũ) → cooldown kiểu cd4 từ
cd4-best 1-2 ep (~3-6h) + retrain policy_prior (~20'). Encoder frozen nên chỉ predictor+policy cần
data; graph/GPS không cần (route tay). Làm được trong 1 ngày.

**7. TOOLING DEBUG MỚI trong `inference_loop.py`: `--step`** — mỗi tick: neutral → in `model steer/ga`
vs `ÁP steer/ga` (thấy floor/EMA/gain làm gì) + **quét E(steer) 5 nấc sống tại tick đó** (thấy CEM
"nghĩ gì") → CHỜ ENTER mới áp đúng 1 nhịp `--pulse-move` rồi coast; `s`=skip, `q`=bỏ route. Log
thường cũng in thêm `(ga model ±x.xxx)`. Fix kèm: `--help` hết crash (escape `%%` help steer-gain).

**8. HISTORY/REACH vs META — RÀ LẠI, KHÔNG PHẢI THỦ PHẠM:** inference ta cấp **1 frame context**
(z0=(1,N,D)) — Meta MPC cũng 1 frame (`mpc_utils.py:48`); `history=2` chỉ là cửa sổ trượt khi
rollout tự hồi quy, khớp pattern train block-causal (temporal_pos re-base về 0 nhất quán train↔infer
— đã soi `vjepa2_ac_car.py rollout`). Reach-check: Meta KHÔNG có detector "đã tới goal" online
(episode chạy đủ N bước rồi đo offline) — GPS-reach outdoor + ccos indoor của ta là phần TỰ CHẾ,
nay đã đo+fix (mục 1). "Meta chính xác cao" = tay máy quasi-static in-domain, không quán tính,
không domain-shift — không so trực tiếp được.

**9. cd8 (T=8, auto_steps 3) PAUSE @ ep0 gstep 3051/4509 (~68% ep0 sau 6h20' → ~9.3h/ep, 3 ep ≈ 28h):**
2 lần OOM trước khi chạy được (batch 64→40 + grad-ckpt + expandable_segments); `last.pt` lưu sạch
09:17, resume = chạy lại đúng lệnh (tmux `train_cd8`, `resume: auto`). **Khuyến nghị: ƯU TIÊN data
indoor (mục 6) trước cd8** — cd8 là ablation B5 "gain nhỏ-vừa nếu có", 28h GPU không giải quyết
OOD indoor. Diff `train_ac_car.py` (auto_steps generic) + config cd8 đã commit.

**10. "GPS NGU — trong bụi cỏ vẫn báo ĐẠT goal" → `--pop-confirm-cos` MỚI (visual-confirm pop):**
GPS đo được noise ±0.44m median / 1.0m p90 / 3.2m max → reach-m là CỔNG THÔ, không bao giờ xác
nhận được 50cm. Nhưng probe chuỗi subgoal THẬT park (graph route 113m, spacing 4-6m): **centered
cos tách vị trí cả ngoài trời** — tại-chỗ ~1.0, subgoal KẾ ~0.58, cách-2 ~0.37, xa âm (cos thô vẫn
mù 0.95-0.99). → `--pop-confirm-cos 0.75` (0=tắt, default): GPS trong bán kính CHƯA đủ, **ẢNH phải
khớp mới pop** — áp cho pop GPS route TAY + goal CUỐI full-nav (center = mean pool subgoal route;
subgoal giữa route graph vẫn GPS vì control target là lookahead). Ảnh không khớp → route tay
timeout dừng an toàn / full-nav chạy tiếp tới khi khớp. Trần chính xác visual ≈ 0.5-1m tuỳ cảnh
(thr 0.85-0.9 + teach ảnh dày = chặt hơn); cm-grade kiểu Meta là từ ENCODER tay máy (proprioception
sub-mm, quasi-static, in-domain) — khác hệ đo, không phải world model của họ "chính xác hơn".

**11. `--step` BẮT ĐƯỢC BUG SEARCH TẠI TRẬN (chạy thật indoor 06-12) → CEM SEED CANDIDATES:**
log step cho thấy **E(-1.0) thấp nhất (model THÍCH trái) mà CEM ra +0.27 phải** — policy warm-start
(BC park, OOD indoor) mu≈+0.25 + warm σ 0.15 → 32 sample không bao giờ chạm vùng −1 → search bị
policy che mắt (đúng nghi vấn user "bị giới hạn không gian search"). **Fix `cem.py`: mỗi iteration
luôn chèn 5 seed candidate steer [-1,-0.5,0,+0.5,+1] (ga = mu hiện tại)** → elite bắt được đáy
toàn cục, +5 rollout/iter (tick 0.36→0.45s), smoke e2e pass (CEM giờ dám ra ±1.0 khi E bảo vậy).
Fix kèm cùng buổi: (a) **`--settle-s`** (default 0; indoor 0.8-1.0) — sau mỗi nhịp pulse/step CHỜ
xe hết trớn rồi mới lấy frame plan ("chưa kịp dừng đã quyết định tiếp"); (b) **validation
`--throttle-min`**: user truyền 0.09 (> cap 0.055) → box lộn ngược, ga GHIM 0.09 mọi tick →
giờ ap.error khi min>cap + warning khi min>0 (flag này là đáy box, chỉ ≤0 mới có nghĩa = cho lùi;
"ga tối thiểu" = --cruise-throttle).

**12. STEP-SESSION #2 (chạy thật indoor, 12 tick @ subgoal 2) — PHÁN QUYẾT INDOOR TRÊN CKPT HIỆN TẠI:**
- **ccos pop chạy ĐÚNG** (0.231 → 0.837 khi tiến lại gần subgoal — thang centered chuẩn ngoài đời).
- **Nhưng argmin E(steer) NHẢY MỖI TICK** (-1 → 0 → +0.5 → -1 → 0 → +0.5, đổi dấu 6 lần/12 tick),
  spread E chỉ 1.7-7%/tick (park 39%) → trong nhà **landscape = noise**, CEM chọn argmin của noise.
  Seeds đã làm CEM bám đúng argmin (model steer khớp phía E thấp từng tick) — vấn đề KHÔNG còn ở
  search, ở chính MODEL: **OOD indoor là phán quyết cuối — không knob nào tạo ra tín hiệu**.
  2 đường: (a) PARK ban ngày (in-domain, mọi fix hôm nay dùng được) — đường ra số liệu trước
  deadline; (b) thu 30-60' data indoor → cooldown (mục 6) — fix thật, hậu deadline.
- **Policy prior: BỎ khi indoor** — OOD (BC park) + kickstart đứng-yên ghim mu ga = 0.75·cap
  (log: ga model dính 0.075 cả buổi). Không policy → không kickstart, model tự chọn ga trong box;
  step mode không cần trễ thấp → `--samples 64 --iters 2`. Park CHẠY LIÊN TỤC vẫn giữ policy
  (thắng A2 + cắt trễ 3.5×; seeds giờ phá thế độc quyền search của nó rồi).
- **Ga đề-pa khi đánh lái gắt**: full-lock @0.08 không nhúc nhích (scrub bánh trước) dù đi thẳng
  @0.08 lăn → floor nhịp rời rạc giờ TĂNG theo |steer|: ×1 thẳng → ×1.5 full-lock (cruise 0.08
  → 0.12 khi ôm hết lái).
- **Bộ knob TỐI THIỂU indoor-step (trả lời "sao một đống tham số")**: chỉ 4 số VẬT LÝ phải đặt
  theo xe/sàn — `cap 0.10 / cruise 0.08 (= ma sát sàn, đo 1 lần) / settle 1.0 / pulse-move 0.45`;
  còn lại để default hết (policy off, EMA 0, gain 1). Đống flag còn lại tồn tại vì 2 LỖ ngoài
  model: xe KHÔNG có bộ điều tốc closed-loop (floor/kick = prosthetic ma sát) + model chưa thấy
  domain test (OOD). Meta không cần knob vì tay máy có position-controller + data in-domain.

**LỆNH INDOOR MỚI (thay lệnh cũ — bỏ manual-reach-cos 0.999, sửa cruise>cap, thêm pulse):**
```bash
PYTHONPATH=src python scripts/route_web.py --graph none          # web :8060
PYTHONPATH=src python scripts/inference_loop.py --web --graph none \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt --samples 32 --iters 1 \
  --floor-no-gps --throttle-cap 0.05 --cruise-throttle 0.04 --steer-smooth 0 --pulse
# debug "tại sao nó quyết định vậy": thêm --step (ENTER từng nhịp, in E(steer) sống)
# ngưỡng pop: default mới 0.80/0.40 (thang centered) — nhìn `cos` trên log/web rồi tinh chỉnh
```

## 📸 2026-06-12 — TEACH & REPEAT: route TAY tự chụp trên web (không cần graph/GPS → indoor/chỗ mới) + 6 fix UI

**Yêu cầu user: tự lái remote + chụp subgoal tại chỗ → tạo route ngay, khỏi phụ thuộc ảnh data cũ**
(teach ngay trước run = cùng ánh sáng → né luôn domain-shift đã đo 06-11). ĐÃ XONG, e2e pass 2 lần.

**1. Flow teach (laptop, xe để CH9 ≠ AUTO):** mở web → panel "Route tay" → đặt tên → lái xe remote
tới từng chỗ muốn làm subgoal → DỪNG, chờ ảnh Live mới (≤3s) → **📸 Chụp subgoal** (kèm xy nếu xe
có GPS+graph; thumbnails xem/↩︎ undo được) → lặp (**vào cua chụp DÀY**: trước/giữa/sau cua) → 💾 Lưu
→ gạt CH9 AUTO → ▶ Run. Backend: `route_web.py` (`/api/manual/snap|undo|<name>`, `manual_image`,
save `mode=manual`, activate gửi `subgoals`); ảnh lưu `data/routes/manual/<tên>/NNN.jpg + meta.json`.

**2. Chạy route tay (`inference_loop.py` nhánh manual):** CEM servo thẳng tới ảnh subgoal hiện tại
(không cần graph/localize/Dijkstra). **Pop subgoal:** có GPS cả 2 phía → `< reach-m` (chuỗi pop được);
KHÔNG GPS (indoor) → cosine pooled ≥ `--manual-reach-cos` 0.97 **2 tick liên tiếp**, HOẶC luật tương-đối
"+đã GẦN (≥ `--manual-near-cos` 0.95) mà subgoal KẾ gần hơn RÕ RỆT (+0.02) = đã qua"; hết chuỗi → 🏁
neutral. **An toàn:** `--manual-timeout-s` 60 (1 subgoal quá lâu → DỪNG chờ web — indoor không GPS là
không có stuck-recovery), route thiếu ảnh → state error, ⛔ STOP web như cũ.
- **⚠️ COSINE ALIAS — ĐO ĐƯỢC trong e2e (trả lời nghi vấn user):** cos pooled giữa các CHỖ KHÁC NHAU
  trong park = **0.939–0.968** (ảnh xám đối chứng: 0.556), còn KHÔNG đơn điệu theo khoảng cách →
  ngoài trời cosine tuyệt đối vô dụng (đúng nghi ngờ; vì vậy outdoor pop bằng GPS). Indoor kỳ vọng
  phân biệt tốt hơn (đồ đạc đặc trưng) nhưng **PHẢI tune bằng số thật**: log in `cos` mỗi tick + web
  hiện live — chạy thử lần đầu nhìn cos lúc ĐỨNG TẠI subgoal vs lúc CÁCH 2-3m rồi chỉnh 2 ngưỡng.
- Margin luật tương-đối từng để 0.005 → e2e pop oan (chênh cos giữa các chỗ khác nhau chỉ ~0.01-0.03)
  → siết 0.02 + near 0.95, e2e lần 2 pop đúng 3/3 đều tại cos 1.000.

**3. Manual-only mode (`--graph none` cả 2 script):** không cần file graph — web ẩn map (panel full),
inference_loop từ chối route graph/direct + goal CLI, chỉ nhận route tay. Đây là mode INDOOR/chỗ mới.

**4. UI web fix (đủ các ý user):** 🆕 Mới (reset editor route); 🧹 vết xe + vết vẽ DƯỚI node (hết che)
+ ▶ Run tự xoá vết cũ; đường route casing 2 lớp + mũi tên chiều đi (hết khó nhìn); **trạng thái rõ**:
state tô màu + dòng `📸 subgoal i/n | cos | lái/ga`, banner DÍNH khi 🏁 xong / ⏱ timeout / 🛑 kẹt-dừng-hẳn
/ ⚠ lỗi; **ảnh subgoal ĐANG NHẮM hiện cạnh camera** khi chạy manual; route list hiểu manual (M, "n 📸",
"sửa" mở lại panel teach để chụp tiếp).

**5. Verify:** route_web test-client 12 case PASS; JS `node --check` PASS; **e2e fake-phone + GPU +
ckpt cd4 + policy @32/1**: idle → nhận route → bám (cos 0.556 ảnh xa, steer CEM sống) → pop 3/3 đúng
chỗ → 🏁 → idle; tick 0.36s (enc 0.02 cem 0.33), floor indoor 0.04. Full-nav graph cũ startup PASS.

**5b. FIX chạy-thật indoor đêm 06-12 (lần bật đầu tiên):** app đổi mạng/nền → mở KẾT NỐI MỚI mà
không FIN cái cũ → loop kẹt recv socket câm mãi, conn mới nằm backlog (ss thấy Recv-Q phình), web báo
"offline" dù loop sống. Vá 2 chỗ: (1) không frame > `--reconnect-s` 8s → tự ĐÓNG conn, quay về accept
(tự hồi, khỏi restart — test giả lập A-câm/B-stream PASS); (2) link câm >2s → web hiện state
**no-frame** + hướng dẫn "mở màn hình camera trong app" (phân biệt với offline = loop chưa chạy).
Khi chạy: giữ app FOREGROUND, màn hình camera bật — app nền/tắt màn = frame ngừng.

**6. LỆNH INDOOR (teach & repeat lần đầu):**
```bash
PYTHONPATH=src python scripts/route_web.py --graph none          # web :8060
PYTHONPATH=src python scripts/inference_loop.py --web --graph none \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt --samples 32 --iters 1 \
  --floor-no-gps --throttle-cap 0.05 --cruise-throttle 0.04 --steer-smooth 0.4
```
Outdoor: lệnh park như cũ (graph mặc định) — teach route tay vẫn dùng được, pop theo GPS `--reach-m`.
**Còn mở:** ngưỡng cosine indoor chưa đo thật (nhìn log/web rồi chỉnh); model OOD indoor (chạy
`probe_energy --frames-dir` ảnh nhà trước khi setup xe); A3 bench_relay vẫn NỢ trước khi bánh chạm đất.

## 🚀 2026-06-11 ĐÊM (đợt 2) — TRỄ 1.35s→0.38s (CEM là 97% tick!), lookahead-target heading-aware, A2 đủ bảng, indoor mode

**Plan tổng (user chốt): MỤC TIÊU SỐ 1 = XE CHẠY CHÍNH XÁC** — không đâm lề; mọi thứ khác (sim/3DGS)
là phương tiện, xếp sau. Plan đầy đủ: `~/.claude/plans/oke-v-y-n-u-enchanted-eclipse.md`.

**1. PHÁT HIỆN TRỄ (smoke e2e fake-phone, desktop 5070 Ti):** tick 1.35s = enc **0.03** + nav 0.04 +
**cem 1.32 (97%!)** — encoder 384px KHÔNG phải nút thắt (chỉ 30ms sau warmup), CEM 64×2 trên model
576-token mới là. **`--samples 32 --iters 1` (policy warm-start) → tick 0.38–0.43s (3.5×), không bỏ
frame nào.** Chất lượng giữ nguyên — ĐÃ ĐO (mục 2, dòng (d)). Laptop ngoài bãi
sẽ chậm hơn desktop nhưng cùng tỉ lệ cắt (CEM-dominated). Với tick ~0.4s: `--steer-smooth 0.4`.

**2. A2 GOAL-REACHING cd4 ĐỦ BẢNG (60 window, FROZEN split, samples 64/iters 2):**
| d | CEM/rnd | CEM/tea | Δsteer | Δthrot | (+policy) Δsteer | πΔsteer |
|---|--------|---------|--------|--------|------------------|---------|
| 1 | 0.69→0.68 | 0.97→0.96 | 0.046 | 0.025 | **0.040** | 0.044 |
| 2 | 0.74→0.72 | 0.95→0.92 | 0.157 | 0.041 | **0.078** | 0.024 |
| 4 | 0.80→0.72 | 1.00→0.92 | 0.284 | 0.073 | **0.105** | 0.011 |
| 8 | 0.83→0.83 | 0.98→0.98 | 0.364 | 0.083 | **0.106** | 0.034 |
→ (a) CEM thuần MÙ DẦN theo khoảng cách goal (Δsteer 0.046→0.364) = định lượng đúng nghi vấn user
"subgoal xa = mù"; (b) **policy warm-start giữ 0.040→0.106 (3.4× @d8) → lệnh chạy BẮT BUỘC --policy**;
(c) so v1 (0.055@d1→0.304@d8): cd4+policy tốt hơn ~3× ở d=8. Log: `logs/eval_goal_cd4*.log`.
(d) **@32/1+policy (deploy config, 60 window): Δsteer 0.045/0.086/0.090/0.109, Δthrot ≤0.026,
CEM/rnd 0.68–0.85, πΔsteer 0.044/0.024/0.011/0.034 — NGANG 64/2+policy (0.040/0.078/0.105/0.106)
→ cắt trễ 3.5× KHÔNG mất chất lượng action, CHỐT 32/1** (`logs/eval_goal_cd4_policy_s32i1.log`).

**3. CONTROL-TARGET MỚI: along-track lookahead + HEADING-CAP (`--ctrl-lookahead-m` 2.5, 0=tắt)** —
trả lời câu hỏi user "vào cua cần subgoal dày hơn? 2 cua 90° thì sao?": ĐÚNG. Subgoal 4m cũ mù ở cua
(ảnh target qua góc = mất overlap với view hiện tại → energy không có tín hiệu). Fix trong
`inference_loop.py`: chiếu xe lên polyline route (chỉ-tiến, monotonic), target = node cách ~2.5m
ALONG-TRACK, **dừng sớm nếu heading route xoay ≥~50°** → vào cua target tự DÀY lên, luôn còn overlap;
qua cua tự duỗi về 2.5m. Subgoal `--subgoal-spacing` 4m chỉ còn là mốc nav/pop/web. Route node dày
~0.3–1m nên target advance mượt từng node (không phải waypoint đường-thẳng — node = frame người lái
từng CHỤP TẠI ĐÓ trên quỹ đạo cong).

**4. Fix kèm trong `inference_loop.py` (smoke-test pass cả 2 mode):**
- **`car_xy` NameError ở `--control-only`** (chưa từng gán → recovery crash tick đầu) — init None/tick.
- **Tier kick/cruise theo `spd_est` = max(doppler, dịch-chuyển GPS từ pos_hist)** — doppler 0.00 khi bò
  từng xếp xe-đang-lăn vào tier kick → surge 0.12 giữa cua (= "nhanh nhất đúng chỗ nguy hiểm nhất").
  Kickstart policy cũng dùng spd_est. (KHÔNG đảo floor/turn_slow như plan phác — đảo máy móc sẽ cắt
  kick đứng-yên-thật xuống dưới ma sát tĩnh 0.07 → kẹt lại; tier đúng mới là gốc rễ.)
- **`--floor-no-gps`**: indoor (không GPS) floor = cruise only (không kick — thiếu tín hiệu đứng-yên).
- **Timing breakdown trong log**: `(0.38s enc0.03 nav0.01 cem0.33)` — từ nay nhìn log là biết nút thắt.
- `scripts/probe_energy.py --frames-dir <dir> --goal-image <jpg>`: probe E(steer) trên ẢNH TÙY Ý
  (indoor pre-check trước khi setup xe; tham chiếu contrast park ≈ 0.39).

**5. LỆNH CHẠY MỚI (park, ban ngày, pin đầy):**
```bash
PYTHONPATH=src python scripts/inference_loop.py --web --reach-m 6 --stuck-s 3 \
  --samples 32 --iters 1 --steer-smooth 0.4 \
  --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
  --policy checkpoints/policy_prior/best.pt --throttle-cap 0.065
```
Indoor smoke (control-only): thêm `--control-only --goal-image <jpg> --floor-no-gps --throttle-cap 0.05
--cruise-throttle 0.04`; trước đó chạy probe_energy --frames-dir để khỏi setup chay. A3 bench_relay_test
vẫn NỢ — làm trước khi bánh chạm đất.

## ✅ 2026-06-11 ĐÊM — cd4 XONG + THẮNG B5; RECOVERY v2 CÓ 2 BUG (đo bằng REPLAY OFFLINE) → v2.1; GPS noise đã đo

**1. cd4 HOÀN THÀNH (không phải fail!):** chạy đủ 3 epoch, val 0.5864→0.5760→**0.5693 (ep2 = best)**.
Crash cuối log chỉ là bước final-eval SAU train: load best.pt vào model đã torch.compile (thiếu prefix
`_orig_mod.`) — đã fix `engine/train_ac_car.py` (load vào `getattr(model,"_orig_mod",model)`); best.pt
nguyên vẹn (atomic save đúng nghĩa). **eval_ratio cd4-ep2 (FROZEN split, 2000 window): ratio@1 0.744 /
@2 0.703 / @3 0.697** — thắng ep9 (0.782/0.746) trên CẢ val lẫn ratio → **B5: ckpt chính thức =
`checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt`**. A2 goal-reaching d=1..8 ±policy đang chạy nền
(`logs/eval_goal_cd4.log` / `eval_goal_cd4_policy.log`). Loss "đi ngang 0.5x" = floor identity/aleatoric
như đã chẩn đoán — KHÔNG train thêm trước deadline, đòn bẩy là data (hậu deadline: B/C).

**2. RECOVERY v2 — 2 bug tìm thấy bằng replay offline 340' GPS người lái (180 session,
`scripts/replay_stuck_detector.py` — KHÔNG cần xe/công viên/GPU):**
- **Bug A: default `--stuck-s 2.0` KHÔNG BAO GIỜ bắn** — prune `> stuck_s` + tick vòng lặp 1.36s →
  span tối đa 1.36s < ngưỡng 0.7×2.0=1.4s. Detector chết im lặng (tối qua bắn được là nhờ stuck-s 3).
- **Bug B: ngữ nghĩa net-displacement-từ-đầu-cửa-sổ bắn OAN 0.86 lần/phút** (72% trigger là xe đang
  đi tiếp >1m trong 3s kế) — không phân biệt "kẹt 3s" với "đứng 2s rồi VỪA đề-pa" → đúng hiện tượng
  "xe tiến lên xong nó lùi".
- **v2.1 (đã vào `inference_loop.py`, validate cùng replay): oan 0.86 → 0.06/phút (stuck-s 2.0) /
  0.015 (3.0)**. 3 vế: (1) giữ 1 mẫu GIÀ hơn stuck_s → span luôn đủ (Bug A hết, mọi stuck-s dùng được);
  (2) phải ĐANG ĐẨY (throt>0.03) suốt cửa sổ — cú kick được trọn stuck_s rồi mới lùi; (3) tick gần nhất
  cũng đứng yên (`--stuck-recent-m` 0.25). Lưu ý đọc số: TRUE-retention trong replay thấp là artifact
  (người lái kẹt thì NHẢ GA ngay nên hiếm mẫu "đẩy liên tục 3s khi kẹt"; chạy thật floor ga giữ lệnh đẩy
  → kẹt cỏ thật sẽ vẫn bắn sau ~stuck_s). **CHƯA test trên xe** — lần chạy tới giữ `--stuck-s 3`.
- **GPS đáng tin tới đâu (user hỏi, đã ĐO — `scripts/measure_gps_noise.py`, 57 đoạn đứng-yên-chắc-chắn):**
  tuyệt đối: scatter median 0.44m / p90 1.0m / max 3.2m → KHÔNG dùng được cho giữ-làn (đường 2-3m);
  hệ hiện tại cũng KHÔNG dùng GPS đánh lái (lái 100% vision). Tương đối cửa sổ 3s: drift median 0.10m /
  p90 0.56m → đủ sạch cho stuck-detect (9.6% cửa sổ 3s vượt 0.6m = miss-rate chấp nhận được);
  advance/pop 3m là borderline 1-2σ (cải tiến sau: pop theo along-track + visual-confirm).
- **"Đạt goal" hiện = GPS < reach_m (6m)** — cả mặt đường LẪN 2 lề cỏ đều nằm trong vòng 6m → xe nằm
  trong bụi vẫn báo reached là ĐÚNG THEO ĐỊNH NGHĨA hiện tại, không phải bug đo. Muốn chặt hơn: goal
  CUỐI thêm visual-confirm (cosine/energy threshold), nhưng trần chính xác METRIC là GPS ±1m; còn việc
  Ở GIỮA ĐƯỜNG là của vision-control (subgoal images vốn nằm giữa đường), không phải của reach-check.

**3. Trả lời "sao model không TỰ lùi dù có data recovery":** by-design lúc inference — CEM box ga =
[0, cap] (`inference_loop.py` `throttle_min=0.0`, "no surprise reverse") + floor ga vô điều kiện +
kickstart clamp mu ≥0.75·cap khi đứng yên → reverse bị CẤM ở planner; data recovery vẫn ăn vào WM
(val giảm mạnh nhờ nó) + policy prior, và node lùi/kẹt bị LỌC khỏi graph có chủ ý (subgoal nhìn-vào-tường
sẽ lái xe vào tường). Option sau deadline: stuck-detector bắn → re-plan 1 LẦN với box [-0.16, cap]
(recovery do model chọn hướng, thay lùi mù `-prev_steer`).

**4. Việc còn mở cho buổi chạy tới (BAN NGÀY + PIN ĐẦY):** lệnh chuẩn như mục A4 + `--stuck-s 3`;
cân nhắc đảo thứ tự floor/turn_slow trong `inference_loop.py` (hiện floor đè turn_slow → vào cua gắt
ở tốc thấp vẫn ăn nguyên kick 0.12 — đúng chỗ dễ văng vào lề); route khó = vẽ thêm waypoint trên web
(Dijkstra penalty tune bằng `&turn=&switch=`).

## 🌙 2026-06-11 TỐI — CHẨN ĐOÁN OFFLINE: ĐÂM-THẲNG LÚC CHẠNG VẠNG = DOMAIN SHIFT ÁNH SÁNG (đã đo), MODEL LÁI TỐT BAN NGÀY + cd4 RESUMED

**Cuối buổi (trời tối) xe đâm thẳng vô cỏ/lề không sửa lái + "lùi quài" → user nghi domain shift, đúng:**
- **Probe A (localize day-vs-dusk, frame thật `live_frame.jpg` 18:03):** ban ngày top-1 sim 0.998,
  top-5 (loại session gốc) CHỤM ~3m quanh vị trí thật; frame tối top-1 0.971, top-5 dính chùm
  0.968-0.969 nhưng VĂNG ~70m khắp công viên → encoder lúc tối chỉ match "đường tối chung chung",
  localize ≈ random trong GPS gate; CEM so ảnh-tối với subgoal-ban-ngày → energy = chênh sáng,
  không phải vị trí → lái như random. **Graph + 209 session đều ban ngày → CHỈ TEST BAN NGÀY**
  (muốn chạy tối: thu thêm session tối + rebuild graph — backlog).
- **Probe B (`scripts/probe_energy.py` MỚI — quét E(steer) [-1,1], throttle=teacher, d=4, 24 turn-window
  val ban ngày, cd4 ckpt):** argmin-E đúng HƯỚNG quẹo **23/24**, median |argmin−teacher| 0.14,
  median contrast (Emax−Emin)/Emin **0.39** — landscape đáy rõ, đúng phía. **Model KHÔNG "đánh lái
  yếu" offline**; lái yếu closed-loop = trễ 1.36s + EMA + (tối nay) domain shift.
- **Run #7-#8 tối:** recovery v2 đo dịch 0.15-0.31m/2.7s ở ga đều 0.07-0.12 — xe thật sự gần như
  không lăn (nghi PIN TỤT ÁP cuối buổi: cùng kick 0.12 đầu chiều chạy 40m). Gate `throt>0.02` của
  floor ga gây nhấp nhả 0.12/0.00 → đã bỏ (floor vô điều kiện khi theo route, commit afdb6dc).
  User tắt recovery (`--no-recover`) → xe đâm thẳng (không tự cứu) → nghỉ vì trời tối.
- **cd4 RESUMED 19:0x (PID 45659): `resume <- last.pt (ep 2, gstep 5647)`** — còn ~1.5 ep ≈ 4-5h.
  Sáng mai: eval theo luật B5 (mục PAUSE dưới) + **A2 eval_goal_reaching d=1..8 ±policy trên ckpt
  thắng** (GPU rảnh sau train) + lần chạy thật kế: PIN ĐẦY + BAN NGÀY + recovery v2 bật
  (`--stuck-s 3`), lệnh chuẩn ở mục A4 dưới.

## 🏆 2026-06-11 CHIỀU-TỐI — A4 CÔNG VIÊN: KỶ LỤC ~40m TỰ ĐI (cd4 + route-cache), 5 fix chạy-thật liên tiếp

**Debug tại trận qua live_status/log, 5 run, mỗi run lộ 1 tầng lỗi mới (commit 7ce1274→165a22e):**
1. **Standstill-attractor policy BC**: đứng yên → policy đề xuất ga ~0 + warm σ 0.01 → CEM ra ga 0.008
   < ma sát tĩnh → kẹt/recovery-lùi vô hạn. Fix: **kickstart** mu ga ≥0.75·cap khi GPS speed < stuck.
2. **Ma sát tĩnh > cap**: pulse 0.45s @0.07 không đề-pa nổi (recovery lùi 0.11 thì đi được!) → kick
   0.12/0.8s. Sau đó phát hiện **--pulse coast ga-0 1.4s không giữ trớn** → bỏ pulse, chạy liên tục.
3. **Doppler speed = 0.00 cả khi đang bò** → recovery cũ false-positive lùi xoá tiến độ → tạm
   --no-recover; cuối buổi viết **recovery v2 displacement-based** (lúc kẹt thật GPS đông cứng ±0.2m
   — tín hiệu sạch; stuck = dịch <0.6m/cửa sổ stuck_s, pos_hist re-arm sau cú lùi). + halted giờ gỡ
   được bằng ▶ Run (trước phải restart). + **ga cruise 2 tầng** (kick 0.12 đứng yên / sàn 0.07 khi
   lăn <0.5m/s — hết surge-coast).
4. **Re-Dijkstra mỗi tick từ cur localize-flicker** → subgoal nhảy giữa session song song (lệch ≤8m)
   → xe lượn. Fix: **route-cache** (plan 1 lần/goal, bám chuỗi cố định, advance = pop; replan chỉ khi
   đổi goal/lạc >off_route_m).
5. **Target đông cứng** (sub = node xuất phát, lệch GPS-node > advance_m không bao giờ pop) → xe servo
   về ảnh điểm xuất phát, "không quẹo". Fix: drop sg[0] + luật pop 2 vế (≤advance_m HOẶC sub kế gần
   hơn). + **OFF-ROUTE deadlock** (gate localize 15m > off_route 10m → node 10-15m kẹt neutral mãi)
   → ép re-localize gate=off_route trước khi neutral.

**Kết quả run cuối: d 56.7→16.7m ≈ 40m tự đi liên tục, subgoal advance mượt route 15→3 (VƯỢT MỐC 26m).**
Còn lại: (a) 2 lần **chui bụi cỏ mép đường ghiền tại chỗ ~27s** ở ga 0.12 (vì --no-recover; v2 đã viết,
CHƯA test trên xe); (b) thoát cỏ bằng đánh lái ±1.0 → view xoay → localize văng → **replan storm**, d
17→46m, user Ctrl+C; (c) xe vẫn lượn ±1m quanh tuyến (chu kỳ 1.36s + EMA 0.6 ì — thử --steer-smooth 0.4).
Lệnh chuẩn lần tới (recovery v2 BẬT): `--web --reach-m 6 --stuck-s 3 --steer-smooth 0.4 --checkpoint
checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt --policy checkpoints/policy_prior/best.pt`.
KHÔNG dùng 1-2m subgoal-spacing (< GPS noise ±2m; ảnh goal ≈ ảnh hiện tại → ga chết). **Nhớ resume cd4
tối nay** (lệnh ở mục PAUSE dưới; còn ~2 epoch ≈ 6h).

## ⏸️ 2026-06-11 16:54 — PAUSE cd4 GIỮA ep2 ĐỂ RA CÔNG VIÊN CHẠY THẬT (A4) — cd4 ĐANG THẮNG, DÙNG NÓ

- **Pause OK** (user ra công viên, cần GPU): SIGTERM PID 9700 → `paused @ ep 2 gstep 5647`, last.pt
  full-state 16:54, GPU trống. **TỐI VỀ RESUME = chạy lại đúng lệnh train cũ** (lệnh chuẩn + env
  allocator ở mục cd4 bên dưới; `resume: auto` đã bật — tự nối optimizer/LR/gstep, làm lại ep2 từ đầu).
- **cd4 ep0-1 val 0.5864 → 0.5760** (vượt best ep9 0.6001 của run 384 ngay từ ep0 — cosine-tail đúng).
- **eval_ratio_ac cd4-ep1 (cùng FROZEN split, 2000 window): ratio@1 0.753 / @2 0.712 / @3 0.706** —
  thắng ep9 (0.782/0.746) trên CẢ val + ratio → theo luật B5, **checkpoint chạy thật/báo cáo hiện tại =
  `checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt`**. Goal-reaching offline (A2) chưa đo — đo sau buổi
  chạy nếu cần; A4 hôm nay là test thật. Lệnh chạy:
  ```bash
  PYTHONPATH=src python scripts/route_web.py     # web :8060, UI mới chọn hướng
  PYTHONPATH=src python scripts/inference_loop.py --web --pulse \
    --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt \
    --policy checkpoints/policy_prior/best.pt --throttle-cap 0.065 --reach-m 6
  ```
  (A3 `bench_relay_test --once --hold 1.2` vẫn CHƯA test — làm trước khi thả bánh xuống đất.)

## 🗺️ 2026-06-11 — ROUTE PLANNER: Dijkstra heading-aware + UI chọn hướng (fix "đường vòng vèo / khó chọn node")

**User báo 3 vấn đề trên web planner → đã fix cả 3, KHÔNG cần rebuild graph (CPU-only, không đụng GPU cd4):**
1. **Đường gợi ý zigzag:** thủ phạm = **251.213 loop-closure edge (vs 33.387 temporal) đều mang weight cứng
   0.5m** trong khi 2 đầu cách thật trung bình 2.6m (p90 5.1m, max 8m) → Dijkstra xâu "teleport rẻ" thành
   đường vòng vèo. Fix `nav/graph.py`: `_build_adj` precompute cost per-directed-edge (mét THẬT
   `max(w,‖XY_u−XY_v‖)` + góc đổi hướng + π khi đi NGƯỢC chiều temporal edge — ảnh subgoal sẽ quay lưng);
   `plan_route(turn_penalty_m=3.0, switch_penalty_m=1.0)` (=0,0 là về shortest-metres cũ). Đo 8 cặp 60–120m:
   nhảy session giảm 3–7× (23→6), tổng góc quẹo giảm 2–4×, mét thật ngắn hơn/bằng, 0 đoạn ngược chiều,
   ~0.06s/leg. Builder từ nay cũng lưu mét thật cho loop edge (`max(loop_weight, dij)`).
   `inference_loop`/`eval_navigation`/`viz_route` dùng chung `plan_route` → tự hưởng (signature tương thích,
   `components()` đã sửa theo adj 4-tuple).
2. **Không thấy hướng đi:** graph vốn LƯU `heading`/node nhưng API+UI không dùng → `/api/graph` trả thêm
   `heading`; UI: node tô MÀU theo hướng (24 bucket hue, toggle ở legend), mũi tên hướng khi hover/selected/
   waypoint, subgoal = tam giác chỉ hướng, waypoint list có glyph hướng, preview hiện "hướng đi: ↗ 52°" (la bàn).
3. **Khó chọn node / không chọn được chiều:** hit-radius 14→22px, node to hơn khi zoom, hover ring + cursor
   pointer, và **chip "node gần đây theo hướng"** trong preview: gom node ≤6m quanh node đang chọn theo 8 hướng
   → bấm chip nhảy sang node gần nhất đi đúng chiều mình muốn rồi mới ➕ waypoint.
- `/api/suggest` nhận thêm `&turn=&switch=` để tune penalty sống. Test: `node --check` JS OK; Flask test-client
  graph/suggest/index OK; components=1 / blocked / extract_subgoals OK. **CHƯA xem trên browser thật** — buổi
  A4 tới mở web là thấy; nếu đường vẫn cong chỗ nào thì chỉnh `turn` (to = thẳng/giữ hướng hơn) ngay trên URL.

## ⚡ 2026-06-11 10:25 — CÚP ĐIỆN giữa ep12 → COOLDOWN T=4 (cd4) ĐANG CHẠY + APK v0.5-pro ĐÃ CÀI

**Sự cố:** run 384/P2 chết vì cúp điện giữa ep12 (last.pt = ep11 ghi 10:11 → chỉ mất ~14').
Ckpt KHÔNG lưu optimizer state + trainer không có resume → không tiếp cosine cũ được (mà cũng
không nên — xem chẩn đoán). best.pt = **ep9, val 0.6001**.

**Chẩn đoán (xác nhận nghi vấn user "epochs quá lớn → cosine LR giảm chưa kịp → loss đi ngang"):**
- val ep0-11: 0.7937 0.6984 0.6862 0.6566 0.6407 0.6177 0.6195 0.6083 0.6052 **0.6001(ep9)**
  0.6044 0.6062 — đi ngang/nhích lên 5 ep cuối trong khi train vẫn giảm (0.5601→0.5538).
- cosine `epochs: 60` = 7.2 ngày @2.87h/ep → tại ep11 **LR còn ~94% đỉnh** (2.35e-4); kể cả
  early-stop ~ep21 (patience 12 từ ep9) LR vẫn ~77% → **cosine tail không bao giờ chạy**.
  epochs=60 đúng là mis-sized vs budget thật; flat = pha "stable" kiểu WSD ở LR cao.
- Caveat: một phần phẳng là floor thật (identity/aleatoric) — cooldown kỳ vọng ăn thêm VÀI %,
  không phải phép màu.

**Eval best.pt ep9 (script MỚI `scripts/eval_ratio_ac.py` = final_eval standalone, 2000 window,
FROZEN split):** **ratio@1 0.782 / ratio@3 0.746** — vượt v1 final (0.826/0.775) và ep4 (0.816).
→ Số A1 đã có; checkpoint hiện tại đã là model tốt nhất từ trước tới nay.

**Cooldown T=4 `cd4` ĐANG CHẠY (PID 9700, start 10:59, 3 ep ≈ 8.6h → xong ~20:00 tối 06-11):**
- `configs/train/vjepa_ac_car_cd4.yaml`: epochs 3, lr 1.2e-4 (~0.5× đỉnh) cosine→0,
  warmup_frac 0.02, `init_from` best.pt ep9, out_dir `checkpoints/vjepa_ac_car_cd4`.
  KHÔNG đổi gì khác (T=4, batch 64, data, objective y nguyên) → gain quy 100% cho LR-decay
  (ablation sạch cho báo cáo, trả lời thẳng câu hỏi schedule).
- **B1 init_from ĐÃ PATCH** vào `engine/train_ac_car.py` (B/C sau dùng được luôn).
- split.json đã copy sang cd4 (B4) — log xác nhận `FROZEN <- split.json` 167/42.
- Theo dõi: `tail -f logs/train_ac_car_cd4.log` (nohup trực tiếp env python, không conda-run).
- ⚠️ Phát hiện: `docs/split_vjepa_ac_car.json` (backup repo cũ) là SPLIT KHÁC (211 ss, val khác
  hẳn) — **đã refresh = bản live 209 ss (167/42)** mà run 384 + cd4 thực dùng.
- ⚠️ **OOM launch #1 (PID 6511, 10:35)**: inductor backward materialize attention
  (64,8,2312,2312) bf16 = 5.1GiB, pool phân mảnh 5.77GiB reserved-unallocated (run vốn sát trần
  15.7/16.3 + sd init_from nằm GPU). Fix: init_from load `map_location="cpu"` + `del sd`, và chạy
  với **`PYTORCH_ALLOC_CONF=expandable_segments:True`** → launch #2 qua khỏi điểm chết, GPU 100%.
  **Từ nay mọi run batch64/384 NÊN bật flag này.** Launch #3 (PID 9700) = relaunch lần cuối để
  lấy trainer mới có RESUME (mục dưới); mất ~45' ep0 — chấp nhận, đổi lấy run pause/resume được.

**🆕 TRAINER CÓ PAUSE/RESUME ĐẦY ĐỦ (yêu cầu user 06-11, đã e2e-test save→pause→resume trên CPU):**
- `last.pt`/`best.pt` giờ lưu **FULL state** (model + optimizer + gstep + best/since) — file ~470MB.
  Save **ATOMIC** (tmp+rename) → cúp điện giữa lúc lưu không phá ckpt cũ. Script eval/inference cũ
  không ảnh hưởng (chỉ đọc key cũ).
- `train.resume: auto` (đã bật trong config cd4): **chạy lại đúng lệnh cũ là tự nối tiếp** —
  weights + optimizer + bước LR + early-stop counter; không có last.pt thì rơi về `init_from`/fresh.
  `resume: <path>` để chỉ định file. Ckpt format cũ (weights-only) resume được nhưng optimizer mới.
- `train.save_steps: 600` (~36'): lưu giữa epoch → cúp điện chỉ mất ≤36' thay vì cả epoch (2.87h).
  Resume từ ckpt giữa-epoch = làm lại epoch đó (reshuffle) nhưng gstep/LR đi tiếp — chấp nhận.
- **PAUSE để lấy GPU đem xe ra chạy: `kill <PID>`** (SIGTERM/Ctrl+C) → train hoàn tất step hiện tại,
  lưu last.pt, in `paused @ ep .. gstep ..`, thoát code 0. Chạy thử xong → chạy lại đúng lệnh train
  cũ → in `resume <- ...` và đi tiếp. (Nếu signal rơi lúc đang VAL: pause có hiệu lực ở step đầu
  epoch kế — trễ tối đa vài phút.)
- **ĐỔI CHIẾN LƯỢC TRAIN:** sửa yaml (lr/epochs/...) rồi resume — optimizer giữ, schedule tính lại
  theo cfg mới từ gstep hiện tại; hoặc `init_from: <ckpt>` + `resume` tắt = lấy weights, optimizer
  mới hoàn toàn (như cd4 làm từ best.pt ep9).
- Lệnh chuẩn (THÊM env allocator):
  ```bash
  PYTORCH_ALLOC_CONF=expandable_segments:True PYTHONPATH=src nohup \
    ~/miniforge3/envs/ai/bin/python -u scripts/train_ac_car.py \
    --config configs/train/vjepa_ac_car_cd4.yaml configs/model/vjepa_ac_car.yaml \
    > logs/train_ac_car_cd4.log 2>&1 &
  ```
- Fix kèm: DataLoader `pin_memory` chỉ bật khi cuda (trước đây run CPU cũng đòi CUDA mem → crash
  khi GPU bận).

**APK v0.5-pro ĐÃ CÀI lên A42** (`versionCode=5` xác nhận qua dumpsys; trước đó máy chưa từng có
v0.4/v0.5). Còn thiếu phần test của A3: `bench_relay_test.py --once --hold 1.2` (cần phone cắm
lại ESP32 + CH9 AUTO + xe kê giá — phone đang cắm PC).

**Khi cd4 xong (tối 06-11) — quyết định theo luật B5:**
1. `PYTHONPATH=src python scripts/eval_ratio_ac.py --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt`
   → so 0.782/0.746 của ep9.
2. A2 goal-reaching d=1..8 (±`--policy`) trên ckpt THẮNG (GPU rảnh sau train).
3. **Giữ cd4 CHỈ KHI không xấu đi** (val + ratio + goal-reaching); ngược lại giữ best.pt ep9.
   Ghi kết quả vào đây kể cả negative (vẫn là ablation schedule tốt cho báo cáo).
4. Tiếp A3-test → A4 chạy thật bãi thoáng → A5 chốt bảng. **KHÔNG khởi động B(T=8)/C trước deadline.**

## ▶️ 2026-06-11 — PLAN SAU KHI RETRAIN 384 XONG (session sau: làm mục này theo thứ tự A→B→C)

> Viết sau buổi rà soát sâu vs code Meta (`reference/vjepa2/`) + paper, trả lời user về
> frames/PE-RoPE/input/augmentation. Run 384/P2 lúc viết: **ep7 val 0.6083** (0.7937→0.6083 giảm
> đều, ~2.87h/ep, patience 12) → dự kiến xong ~**2026-06-13**. **Deadline 06-15 → Phase A là đường
> găng; B/C là hậu-deadline.** KHÔNG restart run đang chạy vì bất kỳ lý do gì bên dưới.

**Căn cứ mới đã VERIFY 2026-06-11 (đối chiếu code thật cả 2 phía, không suy diễn):**
- **Frames:** Meta AC paper train **16f@4fps=4s** (paper dòng 795) nhưng config CÔNG BỐ chỉ **8f=2s**
  (`configs/train/vitg16/droid-256px-8f.yaml`); ta 4f@220ms — **Δt khớp Meta (250ms)**, context ngắn hơn.
  **CEM inference Meta chỉ dùng 1 frame context** (`notebooks/utils/mpc_utils.py:48`), ta history=2 →
  context dài chủ yếu giúp LÚC HỌC (block-causal train mọi context length 1..T), không phải lúc chạy.
  Encoder cả 2 phía đều encode TỪNG frame (Meta nhân đôi frame thành tubelet tĩnh, `vjepa_droid/train.py:410`)
  → bài "pretrain 16→64 frames tốt hơn" KHÔNG chuyển giao sang AC (encoder frozen + per-frame).
- **Augmentation:** RRC trong config công bố của Meta là **DEGENERATE** — `random_resize_scale` ghim
  [1.777,1.777] → với video 16:9, `_get_param_spatial_crop` (cần aspect≥3.16) fail cả 10 lần → **LUÔN
  fallback center-crop cố định** (h=720, w=1.35·720, squash 256²), hflip=false ⇒ **zero randomness**.
  (Paper *nói* RRC aspect 0.75–1.35 — code công bố kể khác.) → việc ta KHÔNG augment (cache latent
  offline, đổi lấy 50–100× tốc độ) không phải lệch đáng kể so với recipe reproduce được; ghi vào
  `VJEPA2_AC_CAR.md` §5b làm căn cứ "no-aug".
- **RoPE:** Meta = 3D-RoPE trong Q·K **mọi layer** (`src/models/utils/modules.py:114-263`), head_dim chia
  3 khối t/h/w (+dư không xoay), **a/s token chỉ xoay temporal** (dòng 184-206), spatial snap về grid
  (`*= grid_size/H`, dòng 180-181), KHÔNG có abs-PE nào trong predictor. **Không patch RoPE vào ckpt
  learned-PE được** (đổi hình học Q·K = phá weights) → RoPE = retrain (Phase C), không phải "fix".
- **Cooldown T=4→8 HỢP LỆ trên best.pt hiện tại:** `temporal_pos` đã cấp sẵn `max_frames=16` slot
  (slot 4..15 còn ~init std0.02, WD tích lũy ~0.4% — dùng làm init OK); mask/dataset generic theo T.
  Chi phí ~2.9× FLOPs/window (seq 2312→4624, attention ~43% FLOPs) ≈ **8-9h/ep @batch32** → 2-3 ep ≈
  1 GPU-ngày. Kỳ vọng gain NHỎ-VỪA, **không có ablation công bố nào** cho AC-context (Meta còn cắt 16→8
  và deploy 1-frame) → làm SAU deadline, đo A/B nghiêm túc (B5).
- **LN-rollout:** fix đã trên disk (`engine/train_ac_car.py:65`), lệch đã định lượng 0.58% term rollout
  → run hiện tại không restart; mọi run sau (B/C) tự có fix. Input run hiện tại đã xác nhận đúng cấu trúc
  Meta: interleave (a_t,s_t,z_t)→ẑ_{t+1}, L1 TF+2-step, per-token LN; khác CÓ CHỦ Ý: action = LỆNH stick
  [steer,throttle×6.67,domain] (xe không có pose → không làm Δstate như Meta được; CEM phải xuất lệnh servo),
  state 12-D IMU+prev-action thay pose 7-D.

### Phase A — NGAY khi train xong (đường găng deadline; mục tiêu xong trước 06-15)
- **A1. Verify run:** `tail -20 wandb/latest-run/files/output.log` — lấy best ep/val + dòng cuối
  `rollout@1 … (×identity …)`; so v1 (ratio 0.826) và ep4 (0.816). Nếu process chết giữa chừng:
  `best.pt` vẫn hợp lệ (ghi mỗi epoch).
- **A2. Offline goal-reaching + A/B policy warm-start** (GPU đã rảnh):
  ```bash
  PYTHONPATH=src python -u scripts/eval_goal_reaching_ac.py --distances 1 2 4 8 --n-windows 60
  PYTHONPATH=src python -u scripts/eval_goal_reaching_ac.py --distances 1 2 4 8 --n-windows 60 \
    --policy checkpoints/policy_prior/best.pt
  # nếu warm-start giúp: thử thêm --samples 64 --iters 2 (đo được phép giảm trễ closed-loop không)
  ```
  So bảng v1 (CEM/rnd 0.74–0.80, Δsteer 0.055@d1, Δthrot ≤0.064). d=16 bỏ (quá chậm, subgoal thật d≤8).
- **A3. Cài APK v0.5-pro + test P0 an toàn** (APK chưa từng cài; kê xe lên giá, bánh hổng):
  `~/Android/Sdk/platform-tools/adb install -r robot/android/app/build/outputs/apk/debug/app-debug.apk`
  rồi `python scripts/bench_relay_test.py --once --hold 1.2` → echo phải RAMP về 0 trong ~0.5–0.9s
  (keep-alive an toàn). Test luôn `--stale-s`/`--off-route-m` nếu kịp.
- **A4. Chạy thật BÃI THOÁNG** (full-nav web hoặc goal đơn; graph 209-session đã rebuild):
  ```bash
  PYTHONPATH=src python scripts/route_web.py            # web :8060 (Tailscale)
  PYTHONPATH=src python scripts/inference_loop.py --web --pulse \
    --policy checkpoints/policy_prior/best.pt --throttle-cap 0.065 --reach-m 6
  ```
  Ghi log + quay video; đếm: mét tự đi, số recovery, số can thiệp. Mục tiêu: vượt mốc 26m (06-09).
- **A5. Chốt bảng số liệu báo cáo:** (1) ratio@1/@3 v1-vs-384, (2) eval_goal_reaching d=1..8 (±policy),
  (3) π policy offline (med|Δsteer| theo d), (4) graph 33.590 node / 1 component / localize 2.0m / <8m 86%,
  (5) chạy thật (mét + can thiệp), (6) bảng deviations vs Meta (§5b + finding RRC-degenerate ở trên).
  **KHÔNG khởi động B/C trước khi A xong.**

### Phase B — Cooldown T=8 (+auto_steps 3) trên best.pt (~1 GPU-ngày; CHỈ sau A, hậu deadline)
- **B1. Patch `engine/train_ac_car.py`** (chưa có init_from/resume — đã check): sau `build_model`+GC-enable,
  TRƯỚC `torch.compile` (dòng ~170-175), thêm:
  ```python
  if tcfg.get("init_from"):
      sd = torch.load(tcfg["init_from"], map_location=device)["model"]
      model.load_state_dict({k.replace("_orig_mod.", "", 1): v for k, v in sd.items()})
      print(f"[ac_car] init_from {tcfg['init_from']}")
  ```
- **B2. (cùng patch, tuỳ chọn) auto_steps=3 trong `_losses`:** gate `tcfg.get("auto_steps", 2)`; sau p2
  thêm bước p3 (re-LN p2 → cat ctx → predict, L1 vs `z[:,3]`, cần `z.size(1)>=4`). Các bước rollout dùng
  seq ngắn (1..k×578) nên rẻ hơn nhiều so với tăng T — đây là knob nhắm thẳng drift d=8.
- **B3. Config mới `configs/train/vjepa_ac_car_cooldown8.yaml`** = copy `vjepa_ac_car.yaml`, đổi:
  `horizon: 8`, `max_gap: 2` (**bắt buộc** — span 14 row, chưa đo tỉ lệ dính gap), `batch_size: 32`,
  `lr: 7.0e-5` (~0.3×), `warmup_frac: 0.0`, `epochs: 3`, `patience: 3`, `compile: false` (tránh
  recompile storm với T=8/1/2/3), `auto_steps: 3`, `init_from: checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt`,
  `out_dir: checkpoints/vjepa_ac_car_cd8`. Model config GIỮ NGUYÊN (`max_frames: 16` đã đủ).
- **B4. BẮT BUỘC copy split** (frozen_split đọc cạnh out_dir, nếu thiếu sẽ TỰ SINH SPLIT KHÁC → eval sai):
  `mkdir -p checkpoints/vjepa_ac_car_cd8/vjepa_ac_car && cp checkpoints/vjepa_ac_car/vjepa_ac_car/split.json
  checkpoints/vjepa_ac_car_cd8/vjepa_ac_car/` (backup repo: `docs/split_vjepa_ac_car.json`).
- **B5. Luật quyết định (A/B cùng protocol):** final_eval ratio@1/@3 + eval_goal_reaching d=1..8 trên CÙNG
  split. **GIỮ ckpt cooldown CHỈ KHI d=4/8 cải thiện mà d=1 không xấu đi**; ngược lại giữ best.pt cũ.
  Ghi kết quả vào đây kể cả negative (vẫn là ablation tốt cho báo cáo). Inference vẫn `history=2`
  (`--history 4` chỉ thử offline — trễ CEM tăng theo seq).

### Phase C — v3 retrain RoPE + T=8 (hậu deadline; ~0.5 ngày code + 3-4 GPU-ngày)
- **C1.** Vendor từ `reference/vjepa2/src/models/utils/modules.py` (MIT): `rotate_queries_or_keys` +
  `ACRoPEAttention` + `ACBlock` (+ `build_action_block_causal_attention_mask` từ cùng file) →
  `src/jepa_wm/models/rope_modules.py`. head_dim 64 → d/h/w = 20/20/20 + 4 dim không xoay; `grid_size=24`
  (24×24 @384px; snap cho phép chạy 256px sau này).
- **C2.** `VJEPA2ACCar(use_rope=True)`: thay `nn.TransformerEncoder` bằng stack ACBlock; **BỎ
  `temporal_pos` + `token_pos`** (Meta không có abs-PE trong predictor); GIỮ patch/action/state_embed +
  norm + head + mask; a/s token đi nhánh temporal-RoPE (modules.py:184-206). Thêm flag vào
  `configs/model/` + registry.
- **C3.** Train T=8 / stride 2 / auto_steps 3, CÙNG split, đo đúng protocol B5. Đây là run "faithful-PE"
  cho paper (đóng nốt deviation pos-emb ở §5b).
- **C4. Backlog sau C:** ablate prev-action (state 12→10, đã hẹn 06-09); multi-crop offline aug K=2-3
  (~9 GPU-h + ~190GB đĩa) — ưu tiên THẤP NHẤT (recipe công bố Meta thực chất không random; phone remount
  giữa 181 session đã là augmentation tự nhiên). Đòn bẩy lớn nhất vẫn là THÊM DATA.

## 📋 2026-06-10 (đợt 3) — RÀ SOÁT vs META + PAPER PACK + APP v0.5-pro (không đụng GPU)

**1. Rà soát ML vs code/paper Meta gốc (`reference/vjepa2/`) — KẾT LUẬN: faithful, không có bug P0 mới.**
Đã đối chiếu từng phần với `src/models/ac_predictor.py`, `app/vjepa_droid/train.py` (config
`droid-256px-8f.yaml`: auto_steps=2, loss_exp=1, normalize_reps=true), `notebooks/utils/mpc_utils.py`:
- ✅ Khớp Meta: interleave `[a,s,patch]`/frame, block-causal, predict tuyệt-đối (residual=false),
  L1 teacher-forcing + 2-step rollout (= auto_steps 2), per-token LN cả dataset lẫn re-LN khi rollout,
  CEM energy L1 final-patch, ImageNet mean/std. Lệch CÓ CHỦ Ý đã ghi ở `docs/VJEPA2_AC_CAR.md` §5b
  (pos-emb học được thay RoPE, depth 12/512 thay 24/1024, state IMU thay pose).
- Lệch nhỏ chấp nhận: Meta CEM trả **mean** + momentum, ta trả best-elite (có EMA steer bù);
  resize 640×360→vuông (méo aspect nhưng nhất quán train↔infer).
- Fix docstring stale (ac_clip/train_ac_car nói "z-score lat_mean/std" — thực tế per-token LN).

**2. CEM nâng cấp theo PiJEPA (đã đọc paper, xem mục 3): `CEMPlannerAC` giờ có σ PER-DIM**
(`sigma0 = min(init_std, nửa-box)` — trước σ=0.5 trên box ga [0,0.08] → ~94% sample dính biên =
bang-bang) **+ warm-start σ NHỎ khi có `mu_init`** (`warm_sigma = max(warm_std·nửa-box, min_std_d)`,
PiJEPA Alg.1 clamp σ∈[0.01,0.05] quanh prior) + `min_std` per-dim. `inference_loop --warm-std`
(default 0.15). ✅ smoke-test CPU pass. **Việc sau train:** A/B `eval_goal_reaching_ac --policy …`
(warm σ mới sẽ làm CEM hội tụ nhanh hơn → thử giảm samples/iters tiếp).

**3. Paper pack đã TẢI về `docs/` (lần sau khỏi tải):** `PiJEPA_…pdf` (arXiv:2603.25981 — "Policy-
Guided World Model Planning…", warm-start MPPI từ policy prior trên JEPA-WM; ta làm đúng tinh thần,
khác: CEM thay MPPI, BC-MLP thay Octo), `V-JEPA_Revisiting…pdf` (V-JEPA 1, 2404.08471),
`ViNG…pdf` (2012.09812) + `ViKiNG…pdf` (2202.11271) (nền của nav graph).

**4. App Android v0.5-pro (build OK, APK `app-debug.apk` — CHƯA cài, user chốt chỉ build):**
- **Fix logic:** SessionPlayer đọc actions.csv trên thread nền (hết ANR session dài);
  SessionList `drive.stop()` trong onDestroy (hết leak 1 thread/lần mở); Uploader bỏ qua session
  đã `.uploaded` (hết gửi trùng); PcLink queue đầy → bỏ frame CŨ giữ MỚI (closed-loop bớt trễ);
  `imageToJpeg` crop+scale+rotate 1 lần createBitmap (đỡ ~4× pixel, mát máy hơn khi stream).
- **Drive upload RESUME byte-offset (yêu cầu user):** lưu URI resumable vào `.drive_upload_uri`
  cạnh session + giữ zip trong cache giữa các retry + `Zips` ghi entry time = mtime (zip
  deterministic) → rớt 5G giữa zip lớn → lần sau hỏi offset (308/Range) gửi TIẾP, không từ 0.
  Session URI hết hạn (404/410) → tự init lại.
- **UX/HUD mới (user chọn ưu tiên closed-loop):** HUD HTML màu — REC đỏ đậm, telem xanh/đỏ,
  mode **AUTO** xanh dương nổi bật, và dòng mới `PC↓ lái/ga · tuổi-lệnh · FRESH/RAMP/STALE`
  (quan sát relay keep-alive ngay trên màn khi chạy AUTO). Version 0.5-pro (versionCode 5).
- Cài khi tiện: `~/Android/Sdk/platform-tools/adb install -r robot/android/app/build/outputs/apk/debug/app-debug.apk`
  (v0.4-safe chưa từng cài — v0.5 bao gồm cả keep-alive an toàn của v0.4).

## 🔎 2026-06-10 — RETRAIN 384 ĐANG CHẠY + RÀ SOÁT CODE TOÀN PIPELINE (fix P0 cho inference/eval)

**Retrain 384/P2 ĐANG CHẠY** (start 2026-06-09 23:41, PID xem `nvidia-smi`): ep0 train 0.9345 /
val 0.7937 / **10451s ≈ 2.9h/EPOCH** (chậm hơn ước 15-25h nhiều — 60 ep = ~7 ngày; patience 12,
v1 cũ best @ep14 → kỳ vọng early-stop ~ep26 ≈ 3 ngày ≈ **xong ~2026-06-13, SÁT deadline 15**).
- **Tiến độ ep0-4** (đo 2026-06-10 chiều): val 0.7937→0.6984→0.6862→0.6566→**0.6407**, giảm ĐỀU
  mỗi epoch (chưa plateau; chậm dần là bình thường — identity floor, xem dưới). Đánh giá CPU trên
  best.pt ep4 (48 val window): val 0.6407 = **TF 0.3075 + rollout 0.3331**; per-step L1 0.306 vs
  identity |z1−z0| 0.375 → **ratio@1 ≈ 0.816 NGAY Ở EP4 — đã vượt v1 final 0.826**. On-track.
- **LN mismatch (P1 đã fix trên disk) ĐÃ ĐỊNH LƯỢNG = KHÔNG đáng kể:** trên best.pt ep4,
  2-step rollout feed-back KHÔNG-LN (= code cũ trong RAM đang train) 0.3331 vs CÓ-LN (= rollout()
  eval/CEM) 0.3351 → lệch **0.58%** của term đó (~0.3% tổng loss). Lý do: prediction đã gần-LN sẵn
  (per-token |mean| 0.0004, std 0.908). → **KHÔNG restart run**; eval bằng rollout() có LN vẫn ổn.
- ⚠️ **`logs/train_ac_car_384.log` RỖNG vì `conda run` nuốt stdout** — theo dõi bằng
  `tail -f wandb/latest-run/files/output.log` (hoặc wandb web `rc-car-jepa`). Lần sau chạy
  `conda run --live-stream` hoặc gọi thẳng `~/miniforge3/envs/ai/bin/python`.
- ⚠️ torch.compile **hit recompile_limit(8)** (forward bị gọi T=4/1/2 trong `_losses` + batch lẻ ở val)
  → một phần chạy eager. Lần sau cân nhắc `torch.compile(model, dynamic=True)` hoặc nâng limit.
- `last.pt`/`best.pt` ghi mỗi epoch → có thể eval giữa chừng bằng `best.pt`.

**Rà soát code (phiên 2026-06-10) — ĐÃ SỬA + verify (CPU smoke test, không đụng GPU):**
- **P0 `CEMPlannerAC` thiếu domain token** — model mới action_dim=3 ([steer,throttle,domain]) nhưng
  planner chỉ sample 2-D → sẽ CRASH với checkpoint mới. Fix: `domain=` param (0=KDS, **1=TowerPro**),
  append cột constant sau khi scale (khớp `ACClipDataset`). Override per-call `plan(..., domain=)`.
- **P0 `eval_goal_reaching_ac.py`** đọc `cfg.data.patch_dir` (không tồn tại ở cfg multi-root) → KeyError.
  Fix: hỗ trợ `data.roots`, dataset multi-root (domain ở cột action cuối, tách ra trước khi đưa teacher
  vào planner). ✅ đã chạy thật end-to-end với best.pt ep0 (CPU, tiny) — plumbing OK.
- **P0 `inference_loop.py`**: (1) `fit_dynamics` cũng đọc `patch_dir` → exception → âm thầm fallback
  **unit coeffs k=1** (sai ~10× so với fit 1.59/0.08/0.09!) — fix multi-root + dùng **frozen split.json**
  cạnh checkpoint (trước dùng `split_sessions` có thể lệch split). (2) thêm `--domain-id` (default 1 =
  TowerPro, servo hiện tại) tự bật khi checkpoint multi-root.
- **P1 `CarDynamics.fit` off-by-one yaw**: regress yaw[i] thay vì yaw[i+stride] (step() định nghĩa
  yaw' = k_yaw·steer·speed') — đã fix; k_yaw đổi 0.142→**0.088** (fit multi-root KDS+TowerPro mới).
  Hệ số mới: **k_thr=1.588, k_drag=0.078, k_yaw=0.088**.
- **P1 train/rollout LN mismatch**: `_losses` 2-step rollout feed ẑ1 lại KHÔNG layer-norm, còn
  `rollout()` (eval+CEM) có LN → đã thêm LN trong `_losses` (chỉ ảnh hưởng run SAU, run đang chạy
  dùng code cũ trong RAM — chấp nhận, lệch nhỏ).
- **`ACClipDataset` thêm `max_gap`** (lọc window vắt qua lỗ frame-drop). **Đo trên data thật: 0%**
  window dính gap (181k window train) → run hiện tại KHÔNG bị ảnh hưởng; param chỉ phòng thủ
  (`data.max_gap: 2` nếu muốn bật).
- **`sync.py` default path stale** `data/raw` (đã đổi tên) → giờ quét `raw` + `raw_kds` +
  `raw_towerpro`, dedupe symlink bằng realpath.
- Ghi chú nhỏ: prev-action lúc train = action 1 ROW trước (~110ms), lúc CEM = action 1 STEP trước
  (220ms), lúc inference = telemetry hiện tại — lệch timescale nhẹ, chấp nhận được (lái người mượt).
  `state.py` zero-fill frame thiếu IMU (hiếm). VRAM train 15.7/16.3GB — sát trần, đừng chạy gì thêm trên GPU.

**Việc sau khi train xong:** `eval_goal_reaching_ac.py` (đã multi-root, có `--policy` để A/B
warm-start) → chạy thật bãi thoáng với `--pulse --policy checkpoints/policy_prior/best.pt`.

## 🆕 2026-06-10 (đợt 2) — PiJEPA policy prior + pulse/recovery + graph rebuild (TẤT CẢ KHÔNG ĐỤNG GPU)

**1. PiJEPA-style policy prior (commit e3a8191):** BC policy goal-conditioned π(pooled z_t, pooled
z_goal, state, domain) → [steer,throttle], train trên data người lái với goal = frame cách d~U{1..8}
bước. Dùng để **warm-start mu của CEM** (`CEMPlannerAC.plan(mu_init=)`) → CEM hội tụ nhanh hơn →
giảm samples/iters → giảm trễ. Wire sẵn: `eval_goal_reaching_ac --policy …` (A/B + cột π riêng),
`inference_loop --policy …`. Train: `scripts/train_policy_prior.py` (CPU, ~1.6M params, vài phút;
đọc split/stats từ ckpt WM). **KẾT QUẢ (val, 209 session, `checkpoints/policy_prior/best.pt`):**
π alone med|Δsteer| **0.023–0.027 PHẲNG theo d=1..8**, med|Δthrot| 0.003–0.004 — so CEM v1 cũ
(0.055→0.304 / 0.020–0.064) tốt hơn **2–10×** ở action-recovery. ⚠️ Đây là BC-imitation offline,
KHÔNG đo compounding-drift closed-loop → vẫn dùng làm warm-start cho CEM (đúng triết lý PiJEPA),
không thay CEM. Sau khi WM train xong: A/B `eval_goal_reaching_ac --policy` + thử giảm samples/iters.

**2. Pooled latents 384 — XONG không tốn GPU (`scripts/pool_patch_latents.py`):** pooled = token-mean
của patch cache → derive bằng CPU memmap thay vì re-encode 2 GPU-h. `data/latents_towerpro` (181) +
`data/latents_kds` (28) đã đầy đủ = bước 4b CŨNG XONG.

**3. Graph rebuild 209-session + FILTER node đâm/lùi/kẹt (commit ef31b8b):** user hỏi đúng chỗ —
build cũ lấy MỌI frame stride-5 làm node, gồm cả frame dí-mũi-vào-tường (ảnh subgoal nhìn sát tường
→ CEM lái xe VÀO tường) + frame đang lùi (camera ngược hướng). Fix: `min_node_speed=0.25` +
`skip_reverse` (mặc định BẬT). Kết quả rebuild: **23% node ứng viên bị lọc** (9.790 — chủ yếu data
recovery), graph mới `data/graph/topograph.pt` = 33.590 node / **1 component 100%** / localize
median 2.0m, <8m 86% / extent 106×133m. (5 session GPS-drift bị skip.)

**4. `inference_loop` thêm `--pulse` + RECOVERY (commit 321f3ad):**
- `--pulse` (sense-plan-act): áp action `--pulse-move` 0.45s rồi NGẮT GA (giữ lái) trong lúc
  encode+CEM → drift lúc tính ≈ 0. Trị tận gốc dao động-do-trễ (xe trôi ~0.8m/quyết định ở cap 0.08).
- `--recover` (mặc định BẬT, cần GPS fix): ga tiến mà GPS speed <0.15 m/s quá 2s (= đâm tường/lao
  cỏ/kẹt) → lùi 1.2s + đánh lái ngược (giống ~160 sự kiện người lái) → replan; quá 3 lần/60s → DỪNG
  HẲN chờ người. Trong nhà không GPS fix → tự tắt (khỏi false-trigger bench test).
- ⚠️ CHƯA test trên xe thật. Lệnh chạy thật đề xuất: `--pulse --policy checkpoints/policy_prior/best.pt
  --throttle-cap 0.065 --reach-m 6`.

**Độ trễ — phân tích cho user:** 2.9h/epoch KHÔNG phải do GC (GC chỉ ~1.3×, và bắt buộc vì OOM):
data ×2.6 + 576 token (~2.5-3×) + depth 12 (×1.5) + compile recompile-limit. Để nguyên chạy tiếp.

**5. WEB ROUTE PLANNER (mới, theo yêu cầu user):** chọn đường cho xe trên web — map 2D toàn graph
(pan/zoom, click node → XEM ẢNH frame, dbl-click thêm waypoint), GỢI Ý Dijkstra nối waypoint
(+subgoal preview), mode per-route (`graph` = Dijkstra giữa waypoint / `direct` = servo thẳng),
LƯU route (`data/routes/*.json`), ▶ Run giao route cho xe ĐANG chạy + ⛔ STOP khẩn, live: vị trí
xe + trail + camera ~2fps. Kiến trúc: `scripts/route_web.py` (Flask :8060 — ⚠️ KHÔNG dùng 5060,
port SIP bị Firefox/Chrome chặn; đọc topograph.pt) ↔
file-based ↔ `inference_loop.py --web` (class `WebBridge` watch `data/routes/active.json`, ghi
`live_status.json` + `live_frame.jpg`; idle = chỉ localize; route xong → chờ route mới, không thoát).
UI: `web/route_planner.html` (vanilla JS canvas, không build step). **Đã test:** mọi API (graph/
node_image cả 2 root/suggest/save/activate/stop/live) + WebBridge round-trip (run→status→stop→frame)
✅; CHƯA test với xe thật. Chạy:
```bash
PYTHONPATH=src python scripts/route_web.py                 # web http://100.110.165.40:8060 (Tailscale)
PYTHONPATH=src python scripts/inference_loop.py --web \
  --policy checkpoints/policy_prior/best.pt --pulse --throttle-cap 0.065   # xe nhận route từ web
```
Lưu ý: lệnh active.json cũ bị bỏ qua khi inference khởi động (bấm ▶ Run lại); waypoint advance
theo GPS `--reach-m`; STOP trên web = neutral + chờ (không phải kill process).

## ▶️ VIỆC NGAY (2026-06-09 tối) — THỰC THI RETRAIN 384/P2 (đã chuẩn bị xong, CHƯA chạy)
**Data recovery (lạng→lùi→chỉnh) ĐÃ UP DRIVE đầy đủ.** Toàn bộ CODE retrain-prep đã commit+push
(`b4bb9e4`, đã smoke-test): 384px control, num_tokens 576, prev-action state (state_dim 12),
depth 12, inference gộp nav+control 1 encode, CEM `prev_action_idx`. Plan đầy đủ: `~/.claude/plans/oke-t-i-v-i-b-n-curious-breeze.md`.

**✅ ĐÃ KIỂM TRA + DỌN (2026-06-09 tối, phiên này):**
- Data đã pull + sync xong: `data/raw_towerpro/` = **181 session** (cũ 64 +117 recovery), TẤT CẢ có `actions_synced.csv`+`imu_synced.csv`. Recovery có ga biến thiên thật (throttle std~0.07, reverse 9–14%, range −0.16..0.15).
- **⚠️ ĐỔI TÊN DIR:** `data/raw`→`data/raw_kds` (30 ss), `data/latents`→`data/latents_kds`. `data/raw_mixed` = 211 symlink (OK).
- **⚠️ POOLED LATENTS + GRAPH ĐÃ BỊ XOÁ HẾT:** `data/latents_kds`, `data/latents_towerpro`, `data/latents_mixed`, `data/graph/` đều RỖNG. → ngoài encode *patch 384*, phải **encode lại POOLED (encode_dataset 384)** cho kds+towerpro rồi **rebuild graph từ đầu** (không còn "chỉ thêm session"). Xem step 4b dưới.
- wandb project đổi `lewm-rccar`→**`rc-car-jepa`** (8 config). Dọn dead/one-off vào `archive/` (xem `archive/README.md`); giữ baseline LeWM + pooled cho bảng kết quả. Config path stale đã sửa (`raw_kds`/`latents_kds`).
- Config xe (`vjepa_ac_car.yaml`) đã đúng ViT-L 2.1 384 / 576 tok / state12 / depth12 — user chốt **GIỮ ViT-L**, không đổi ViT-G.
- **Split TÁI LẬP ĐƯỢC:** train ghi `<out_dir>/vjepa_ac_car/split.json` (train/val lần đầu, seed 0, session-level 80/20 = 145/36); các lần sau (cả `eval_goal_reaching_ac.py`) **đọc lại y nguyên** → val set cố định kể cả khi thêm data (session mới bị loại + cảnh báo; xoá split.json để tạo lại). Helper `jepa_wm.data.frozen_split`. ⚠️ split.json nằm cạnh checkpoint (gitignored) → copy ra repo nếu muốn version-control.

**Chạy theo thứ tự (verify từng bước):**
```bash
# 1) PULL data recovery từ Drive → data/raw_towerpro/ (xem robot/tools/pull_drive.py / rclone gdrive:JEPA).
#    Verify: ls -d data/raw_towerpro/session_* | wc -l  (phải > 100, thêm session recovery mới)
# 2) sync (actions_synced + imu_synced cho session mới):
PYTHONPATH=src python scripts/sync_dataset.py
# 3) XOÁ cache 256 (62GB, regen được) rồi encode 384 TOÀN BỘ (~3 GPU-h, ra (N,576,1024)):
rm -rf data/latents_towerpro_patch
PYTHONPATH=src python scripts/encode_patch.py --raw-dir data/raw_towerpro --out-dir data/latents_towerpro_patch_384 --image-size 384
# 4) TRAIN (~15-25h; configs đã set 576/state12/depth12/batch24/patch_dir _384/state_columns +prev). Nếu OOM → batch 16:
PYTHONPATH=src python scripts/train_ac_car.py --config configs/train/vjepa_ac_car.yaml configs/model/vjepa_ac_car.yaml
# 4b) POOLED latents + graph đã bị xoá → encode lại pooled 384 (cho NAV graph) rồi rebuild:
PYTHONPATH=src python scripts/encode_dataset.py --raw-dir data/raw_kds       --out-dir data/latents_kds       --image-size 384
PYTHONPATH=src python scripts/encode_dataset.py --raw-dir data/raw_towerpro  --out-dir data/latents_towerpro  --image-size 384
# 5) eval + rebuild graph (path ĐÃ ĐỔI TÊN: latents_kds/raw_kds; nav vẫn 384):
PYTHONPATH=src python scripts/eval_goal_reaching_ac.py --checkpoint checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt
PYTHONPATH=src python scripts/build_graph.py --root data/latents_kds:data/raw_kds:kds --root data/latents_towerpro:data/raw_towerpro:towerpro --out data/graph/topograph.pt
```
- **Ablate prev-action (nếu kịp):** train lần 2 bỏ `prev_steer, prev_throttle` khỏi `state_columns` (+ state_dim 10) → so Δsteer/dao-động. prev-action là MỞ RỘNG (không phải đúng-Meta) → cần kiểm có giúp không.
- **Sau khi có model mới:** chạy thật ở **bãi THOÁNG** (xe KHÔNG né vật cản) + `inference_loop --reach-m 6` + cài APK **v0.4-safe** (chưa cài: `adb install -r robot/android/app/build/outputs/apk/debug/app-debug.apk`).
- Đòn bẩy LỚN NHẤT = data recovery, không phải 384/depth.

## 🏁 2026-06-09 (đợt 3) — CHẠY THẬT NGOÀI CÔNG VIÊN + rà soát + P0/P1 fixes

**Cột mốc:** xe **TỰ LÁI ~26m** ngoài công viên (full-nav qua Tailscale, gps 31m→**4.9m sát đích**),
rồi dao động mấy mét cuối → trôi → **đâm tường** (không có né vật cản). Lần đầu autonomous thật.

**Đã thêm trong buổi (giúp đi xa được):** `--goal-node/--goal-xy` (chọn goal trên map, `scripts/pick_goal.py`
render map + `--mark-current` định vị xe), `scripts/capture_goal.py`, fix-B advance subgoal theo GPS,
reach theo GPS, smoothing lái (EMA `--steer-smooth` + `--turn-slow`), tối ưu trễ **2.8s→~0.4s** (bf16 CEM
+ samples 64/iters 2), `--control-only`.

**Rà soát 7 nghi vấn + sửa (plan `~/.claude/plans/oke-t-i-v-i-b-n-curious-breeze.md`):**
- **P0 an toàn (DONE, chưa test):** inference `--stale-s` (mất frame >0.4s → neutral), `--off-route-m`
  (localize lệch GPS → neutral); app **keep-alive an toàn** (PC im >500ms → RAMP lái về thẳng + ga 0,
  ngừng hẳn >900ms) → APK **v0.4-safe** (build OK, **CHƯA cài** vì đang thu data).
- **P1:** inference `--fp16-encoder` (hướng <6GB cho laptop, opt-in).
- **GPU 60W/P0:** thủ phạm = **`ollama serve`** (systemd, user `ollama`) giữ GPU. **User chạy:**
  `sudo systemctl stop ollama` (+ `disable`) → kỳ vọng P8/~15W.
- **Multi-frame encode: BÁC BỎ** (xem mục dưới đã sửa) — tốc độ vào qua STATE token, không phải encoder.

**Việc tiếp:** cài APK v0.4 + test P0 (`bench_relay_test.py --once --hold 1.2` → echo ramp về 0);
data RECOVERY (lạng→lùi→chỉnh, đang thu) + approach-and-stop + ga-biến-thiên → retrain; P2: action-trước
vào state + off-route + predictor sâu hơn. **Chạy thật chỉ ở BÃI THOÁNG** (không né vật cản) + `--reach-m 6`.

## 🚗 2026-06-09 (đợt 2) — PHASE 4 closed-loop scaffold + goal-reaching eval + app pass

**Chốt:** ablation dừng, **v1 (full 10-D IMU) = model chuẩn** cho tới khi xe chạy thật được
(user: "kiểu gì hôm nay cũng thu thêm data… ablation để sau"). minimal (2-D) train dở ep8
(`checkpoints/vjepa_ac_car_minimal/`, val 0.5654 ~ kém v1 chút), residual KHÔNG train. Đừng coi
minimal/residual là kết luận.

### Task 3 — `scripts/eval_goal_reaching_ac.py` (MỚI) — goal-reaching offline cho v1
CEMPlannerAC + CarDynamics trên patch-token model (cái `eval_goal_reaching.py` cũ chỉ chạy pooled
`CEMPlannerLatent`). Dataset trả tokens LN'd, state RAW (state_mean=None), action RAW (scale=1) →
planner tự chuẩn hoá. CarDynamics.fit trên train split (k_thr=1.84, k_drag=0.09, k_yaw=0.14).
Kết quả val (v1, 60 window/d) — **CEM/mean<1 = planning hơn random; CEM/tea~1 = sát người lái:**

| d | CEM/rnd_mean | CEM/teacher | Δsteer | Δthrot |
|---|---|---|---|---|
| 1 | 0.74 | 0.96 | 0.055 | 0.035 |
| 2 | 0.75 | 0.92 | 0.144 | 0.020 |
| 4 | 0.77 | 0.92 | 0.316 | 0.046 |
| 8 | 0.80 | 0.92 | 0.304 | 0.064 |

Planning thắng random ở MỌI tầm (0.74→0.80, xấu dần nhẹ theo d), CEM bám teacher ~0.92, Δthrot
nhỏ (ga tốt). Lệnh: `PYTHONPATH=src python -u scripts/eval_goal_reaching_ac.py --distances 1 2 4 8 --n-windows 60`.
⚠️ d=16 RẤT chậm (>30') — bỏ; subgoal cách ~4m ≈ vài step nên d≤8 là tầm hữu ích.

### Firmware AUTO đã VERIFY (đọc code, không assume)
`main.cpp`: `readUsbControl()` (mỗi loop) đọc hex+\n USB → `applyControl` set `autoSteerB/autoThrotB`
+ `lastCtrlMs`; `M_AUTO` (CH9>1700) → `driveNorm(autoSteerB/255*2-1, …)` + watchdog `CTRL_WATCHDOG_MS`
mất gói PC→neutral. Map byte ↔ chuẩn là NGHỊCH ĐẢO của `controller.action_to_bytes` → khớp. Chuỗi
PC→phone→ESP32 đúng ở mức code; còn lại là test runtime.

### ⚠️ TEST TRONG NHÀ (2026-06-09): full-nav KHÔNG chạy được — graph là data CÔNG VIÊN
GPS yếu trong nhà + cảnh trong nhà không có trong `topograph.pt` → `localize` trả node bậy. Trong nhà
CHỈ test được **plumbing** (`scripts/bench_relay_test.py`): phone↔PC↔ESP32 + firmware AUTO + app relay.
Full nav phải ra công viên (có graph + GPS). Test plumbing nên **kê xe lên giá, bánh không chạm đất**.

### ✅ PLUMBING + LATENCY-FIX (#1) ĐÃ VERIFY TRÊN XE THẬT (2026-06-09)
- Chạy `bench_relay_test.py` (lái quét + ga) trên xe (qua Tailscale, phone↔ESP32 USB, CH9=AUTO,
  bánh hổng): **servo lắc + motor quay + echo_steer/throt khớp lệnh, round-trip ✓** → chuỗi
  PC→phone→ESP32 AUTO chạy thật. Firmware AUTO USB không cần sửa.
- **Latency/jitter fix #1 (keep-alive trên PHONE) — DONE + verified.** App v0.3: PcLink chỉ *lưu*
  action từ PC; thread riêng resend ESP32 **@12Hz qua USB** (ngừng nếu PC im >`AUTO_STALE_MS`=1s →
  firmware watchdog 500ms về neutral). PC `inference_loop` đường phone gửi **1 lần/plan** (dongle vẫn
  PC keep-alive). → WAN jitter (5G/Tailscale) KHÔNG còn chạm watchdog. **Verify:** `bench --once --hold 0.8`
  gửi 1 lần/step mà echo giữ ±0.6 suốt 0.8s (bản cũ tụt về 0 sau 0.5s). KHÔNG cần flash firmware.
- ⚠️ Gotcha test: cắm lại phone↔ESP32 phải **app foreground + bấm Allow USB** (telem OK) thì relay
  mới chạy; nếu không `serial.send` no-op (servo đứng im, frames=0).

### inference_loop ĐÃ CHẠY THẬT end-to-end (control-only) + đo VRAM/trễ (2026-06-09)
- Thêm `--control-only` vào `inference_loop.py`: bỏ graph/nav, CEM lái thẳng tới `--goal-image`
  (visual servoing, chạy được TRONG NHÀ không cần GPS). Full-nav vẫn cần park (graph+GPS).
- Chạy thật (phone↔xe, control-only, goal giả = 1 frame park): **VRAM ~7.3 GB** (7463 MiB),
  **~2.8 s/quyết định**, pipeline encode→CEM→action→relay OK; steer biến thiên + throttle ghim +0.15.
- **Trong nhà = OOD** (model train ở park, goal giả không khớp) → steer nhảy loạn (+0.3…+0.81…−0.05),
  KHÔNG phải lái đúng — chỉ chứng minh pipeline chạy. Lái đúng = eval offline (park) Δsteer 0.055 @d=1.
- **Chưa tối ưu** (user hoãn): CEM chạy fp32 + không torch.compile → chậm. VRAM 7.3GB >6GB nên CHƯA
  chạy được laptop 6GB; muốn xuống <6GB+<0.7s thì: autocast bf16 quanh CEM, encoder `.half()`,
  giảm samples/iters, torch.compile. (Đổi ViT-B = mạnh nhất nhưng phải retrain.)

### Task 2 — closed-loop Phase 4 (transport = PHONE RELAY, scope = FULL NAV) — user chốt
**`scripts/inference_loop.py` (MỚI)** — phone TCP frame → V-JEPA encode {nav 384px pooled +
control 256px patch} → `TopoGraph.localize`(+GPS prior)→`plan_route`→`extract_subgoals` → subgoal
patch → `CEMPlannerAC` (MPC horizon 4) → 2-byte action → **gửi NGƯỢC qua chính socket phone**
(`controller.PhoneRelaySender`, khung 3-byte `[0xA5,steer,throt]`) → app relay xuống ESP32.
Goal = `--goal-image` (encode→localize→goal node). FrameReader giữ latest-only (không dồn trễ).
`--dongle` = đi ESP-NOW dongle thay vì phone. **CHƯA test end-to-end** (cần xe + firmware AUTO CH9).

**`robot/capture/controller.py` (VIẾT LẠI)** — bỏ UDP cũ. `action_to_bytes` (Mode-3 đối xứng
`(v+1)/2*255`, **clamp throttle [-0.16,0.15]**), `framed_action`, `PhoneRelaySender` (ghi socket),
`SerialDongleSender` (hex+\n như recorder.py). Verified byte-map (neutral 127/127).

**App Android — relay + state + UX (build OK, `app-debug.apk`):**
- `PcLink`: thêm **downlink** — thread đọc khung 3-byte `[0xA5,steer,throt]` trên cùng socket →
  `onAction` → `serial.send([steer,throt])`. (Firmware chỉ áp dụng khi CH9=AUTO → forward luôn an toàn.)
- `SensorLogger`: giữ **latest** accel/gyro/rotvec/GPS speed+lat/lon (cập nhật cả khi không record);
  `buildMeta` nay kèm `speed,lat,lon,gx..gz,ax..az,rx..rz` → closed-loop có đủ state cho world model.
- **Fix mất data:** `SessionWriter` flush CSV mỗi 30 frame (app bị kill giữa buổi = chỉ mất vài dòng,
  trước đây mất TOÀN BỘ CSV của session đó).
- **Fix Drive:** `DriveUploader` kiểm tra file đã có trên Drive trước khi gửi → chống upload TRÙNG
  (crash sau PUT trước khi ghi marker `.drive_uploaded`). ⚠️ còn 2 hạn chế Drive chưa fix: (1) PUT
  không resume byte-offset (mạng rớt giữa zip lớn → gửi lại từ 0); (2) scope `drive.file` chỉ thấy
  file APP tạo → nếu folder "JEPA" do rclone tạo, app tạo folder JEPA RIÊNG (data phân mảnh 2 chỗ).
- **UX:** đổi IP PC ngay trong app (nhấn-giữ ô status → lưu SharedPreferences, khỏi build lại);
  HUD update ~5Hz thay vì mỗi frame.

### Việc tiếp (closed-loop thật)
1. **Firmware AUTO**: xác nhận `main.cpp` đọc control hex USB + áp dụng khi CH9>1700 (AUTO) +
   watchdog 500ms→neutral. `robot/capture/controller.py` clamp đã khớp envelope an toàn.
2. **Test phone↔PC downlink**: chạy `inference_loop.py` với 1 goal-image, gạt CH9=AUTO, kiểm xe
   nhận action (xem log `[infer] … steer/throt`, và app relay). Bắt đầu kê xe lên giá (bánh không chạm đất).
3. **Thu data ga-biến-thiên hôm nay** (user đang ra ngoài) → sync → encode_patch → retrain v1 + rebuild graph.

## 🌙 2026-06-09 — VJEPA2ACCar (patch-token AC) — ĐÃ TRAIN + KẾT QUẢ

**Model đóng góp chính (`VJEPA2ACCar`, `vjepa_ac_car`) đã train + eval. THẮNG pooled baseline.**

### Kết quả offline (val set, 600 sample):

| Model | rollout@1 ratio | rollout@3 ratio | Checkpoint |
|---|---|---|---|
| **VJEPA2ACCar v1** (10-D IMU, patch) | **0.826** (↓17%) | **0.775** (↓23%) | `checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt` |
| vjepa_ac_pool (pooled, no state) | 0.867 (↓13%) | — | `checkpoints/vjepa_ac_pool_towerpro/vjepa_ac/best.pt` |

- ratio < 1.0 = tốt hơn identity baseline. Thấp hơn = tốt hơn.
- Checkpoint v1: ep=14, val_loss=0.5529. Stopped sớm (patience=12 còn ~12 epoch) để có thời gian ablations.
- **⚠️ torch.compile** lưu weights với prefix `_orig_mod.` → khi load thủ công phải strip:
  `sd = {k.replace('_orig_mod.','',1): v for k,v in ckpt['model'].items()}`
  Đã fix trong trainer + compare_experiments.py.

### Config v1:
- Encoder: V-JEPA 2.1 ViT-L frozen, 256px per-frame → 256 patch tokens × 1024-D (cache `.npy` memmap)
- State: 10-D `[speed, gx,gy,gz, ax,ay,az, rx,ry,rz]`, horizon=4, frame_stride=2, batch=40, lr=2.5e-4
- Loss: L1 teacher-forcing + 2-step rollout (faithful V-JEPA 2-AC)

### Ablation queue (tự động via `scripts/train_overnight.sh`, `logs/overnight.log`):
1. ✅ **vjepa_ac_pool** (baseline pooled) — xong ep23, ratio=0.867
2. 🔄 **vjepa_ac_car_minimal** (state=[speed,gz] 2-D) — đang chạy ep8+, ~19 min/epoch
   - So sánh sơ bộ ep6-8: minimal val ~0.003–0.013 cao hơn v1 (10-D) → 10-D tốt hơn một chút
   - Xem: `tail -5 logs/train_ac_car_minimal.log`
3. ⏳ **vjepa_ac_car_residual** (predict_residual=True) — chờ sau minimal

### Việc tiếp theo (phiên sau):
1. **Đọc kết quả ablations** khi xong: `PYTHONPATH=src python scripts/compare_experiments.py`
2. **Viết `scripts/inference_loop.py`** (Phase 4 — CHƯA CÓ):
   - Kiến trúc: phone TCP stream (JPEG+meta) → PC encode V-JEPA → CEMPlannerAC → action
   - Gửi action về: hiện chỉ có phone→PC (một chiều), cần thêm PC→phone→ESP32
   - **Blocker**: `pc_stream_view.py` chỉ nhận, không gửi ngược. Android app chưa relay action từ PC.
   - Nếu có dongle ESP-NOW: có thể dùng PC→dongle serial thay vì qua phone
3. **Fix `robot/capture/controller.py`**: đổi UDP → serial (dongle), throttle Mode-3 linear map, clamp [-0.16, 0.15]
4. **eval_goal_reaching offline**: CEM planning trên val set, dùng `CEMPlannerAC` + `CarDynamics`
5. **Thu thêm data** nếu ra công viên (FlySky + phone như bình thường)

## 🧭 2026-06-08 — VISUAL NAVIGATION (graph subgoal) + control trên servo hiện tại

**Bài toán đã chốt với user:** "tự lái" = **visual goal-reaching cục bộ + topological graph ảnh
subgoal** (kiểu ViNG/ViKiNG). KHÔNG né vật cản, KHÔNG SLAM. Goal khuất tầm nhìn → giải bằng
**chuỗi ảnh subgoal** xâu các goal-nhìn-thấy-được (mỗi cái CEM cục bộ lái tới). Né vật cản: hoãn/bỏ
nếu kẹt deadline (đã bàn: cần collision-cost từ IMU spike + reactive override; ~160 event va-chạm→lùi
trong data TowerPro có thể auto-label sau).

### Kiến trúc 2 TẦNG (tách bạch — quan trọng)
- **Navigation (action-agnostic = chỉ visual place + GPS):** `src/jepa_wm/nav/graph.py` (`TopoGraph`).
  Node = frame(latent V-JEPA **single-frame** + GPS mét + heading). Cạnh **temporal** (người đã lái =
  chắc đi được) + **loop-closure** (kNN cosine latent cross-session, **GPS-gate <8m** chống aliasing).
  `localize()` (có GPS-prior), `plan_route()` (Dijkstra), `extract_subgoals()` (chuỗi ảnh). Build:
  `scripts/build_graph.py`; eval: `scripts/eval_navigation.py`; viz PNG: `scripts/viz_route.py`.
- **Control (servo-specific):** `vjepa_ac` (V-JEPA 2.1 frozen + ACPredictor 7.4M) + CEM. **MỚI**
  `CEMPlannerLatent` trong `planning/cem.py` (interface `ACPredictor.rollout(s0,actions)`; `CEMPlanner`
  cũ là cho LeWM). Eval: `scripts/eval_goal_reaching.py` (CEM vs random vs teacher + quét độ-xa-goal
  + action-recovery Δsteer/Δthrot).

### Kết quả (verify OFFLINE, không cần phone)
- **Graph 92-session** (28 KDS + 64 TowerPro = 29,699 node): **1 component 100%**, localize LOSO
  **median 2.1m** (<8m 88%), routing **100%**, route bám tuyến người thật **median 2.3m**. Lọc 2
  session GPS-drift (extent>160m hoặc vmax>12 m/s). Artifact: `data/graph/topograph.pt`, `route_viz_92.png`.
- **vjepa_ac trên TowerPro** (encode 98,751 frame → `data/latents_towerpro`, 387MB): rollout@1 ×identity
  = **0.92 (TowerPro-only) / 0.87 (mixed)**. eval_goal_reaching: **CEM/rnd_mean 0.46–0.70**, Δsteer 0.16,
  **Δthrot 0.04**. Checkpoint: `checkpoints/vjepa_ac_{towerpro,mixed}/vjepa_ac/best.pt`.
- **FIX throttle normalization:** `LatentTransitionDataset` thêm `action_scale`; config vjepa_ac dùng
  **[1.0, 6.67]** (như LeWM, đưa throttle ~[-0.15,0.15]→~[-1,1]). Trước đó vjepa_ac coi nhẹ throttle
  (raw nhỏ hơn steering 6.67×) → Δthrot **0.12→0.04**.
- **Codex concern GIẢI QUYẾT (tốt):** mixed-LeWM eval trên **TowerPro-only held-out** = rollout@1 **0.65**
  (vs TowerPro-only model **1.073** = tệ hơn đứng yên!). → **train chéo-domain-servo GIÚP ÍCH**, KDS
  (giàu steering) transfer sang TowerPro. `eval_lewm.py` thêm `--domains <kds680hv|towerpro>` + `--device`.

### ⚠️ VẤN ĐỀ SÂU chưa fix — encode SINGLE-FRAME (xác nhận bằng test)
- `vjepa2_1_vit_large_384` là model **VIDEO**: tubelet_size=2, num_frames=64. Mình feed **T=1** →
  output (576,1024) hợp lệ NHƯNG **latent không có vận tốc**. (Test: T=1→576 tok; T=2→576 = 1 tubelet
  CÓ motion; T=16→4608.) → **lý do sâu của throttle yếu**: frame tĩnh không biết tốc độ; normalization
  chỉ giúp một phần.
- ~~**Multi-frame clip** (feed T=4/8) = nâng cấp chính cho CONTROL~~ ⚠️ **SAI — ĐÃ BÁC BỎ 2026-06-09**
  (xác minh từ source hub + paper + chính `docs/VJEPA2_AC_CAR.md`): model 2.1 vit_large_384 chạy
  **image path tubelet_size=1** (Conv3d kernel t=1 = KHÔNG tích chập thời gian); và doc đã đo
  **clip nhiều frame vào encoder vẫn R²(speed)≈0**. → tốc độ phải vào qua **STATE token** (model đã có),
  KHÔNG phải multi-frame. Chi tiết: plan `oke-t-i-v-i-b-n-curious-breeze.md` PHẦN D.

### Việc tiếp (ưu tiên cho phiên sau / Codex)
1. **Closed-loop N4 (cần phone A42 — user chưa mang theo):** viết `src/.../inference_loop.py` (chưa có):
   phone TCP frame → PC encode V-JEPA → `TopoGraph.localize`+`plan_route`+`extract_subgoals` → CEM
   (`CEMPlannerLatent`) lái tới subgoal → 2-byte action. Sửa `robot/capture/controller.py` (còn UDP cũ →
   serial native; throttle Mode-3 linear; **clamp cứng [-0.16, 0.15]** = giới hạn an toàn của xe).
2. ~~Prototype multi-frame clip cho control~~ ⚠️ **BỎ — đã bác bỏ (xem trên + plan PHẦN D).** Thay bằng:
   cải thiện STATE token (thêm action-trước vào state) + năng lực predictor + chuẩn-hoá action + data ga-biến-thiên.
3. **Data chiều 2026-06-08 (user đang thu):** approach 1 mốc từ 5-10 hướng (=ảnh goal cố định) +
   test-route A→B. Khi về: `scripts/sync_dataset.py` → `encode_dataset.py --raw-dir <batch>` → rebuild
   graph + retrain vjepa_ac.
4. (tùy chọn, rẻ) predictor to/optimize hơn — thứ yếu, encoding mới là bottleneck.

### Tái tạo artifacts (⚠️ `data/` + `checkpoints/` GITIGNORED → phải chạy lại)
```bash
pip install -e .   # 1 lần
# encode TowerPro (nếu thiếu data/latents_towerpro) — phần CHẬM (~10' GPU), V-JEPA 2.1 ViT-L 384
PYTHONPATH=src python scripts/encode_dataset.py --raw-dir data/raw_towerpro --out-dir data/latents_towerpro
# graph 92-session (multi-root, không cần merged dir)
PYTHONPATH=src python scripts/build_graph.py --root data/latents:data/raw:kds \
  --root data/latents_towerpro:data/raw_towerpro:towerpro --out data/graph/topograph.pt
PYTHONPATH=src python scripts/eval_navigation.py --graph data/graph/topograph.pt
PYTHONPATH=src python scripts/viz_route.py --graph data/graph/topograph.pt --out data/graph/route_viz_92.png
# vjepa_ac mixed cần MERGED symlink dirs (tên session unique theo ngày → không đụng):
#   data/raw_mixed = data/raw/session_* + data/raw_towerpro/session_* ; data/latents_mixed tương tự
PYTHONPATH=src python scripts/train.py --config configs/train/vjepa_ac_towerpro.yaml configs/model/vjepa_ac.yaml
PYTHONPATH=src python scripts/eval_goal_reaching.py --checkpoint checkpoints/vjepa_ac_towerpro/vjepa_ac/best.pt
```

## 🌙 Đêm tự động 2026-06-07 — kết quả train cả 2 model (LeWM + V-JEPA-2.1-AC)

**Đã train + đánh giá rigorous CẢ HAI world model. Headline: model chính (vjepa_ac) thắng + ổn định hơn LeWM.**

| Model | rollout@1 / identity (mean±std) | Beats "đứng yên"? | Ghi chú |
|-------|------|------|------|
| **vjepa_ac** (V-JEPA 2.1 đóng băng + AC predictor 7.4M) | **0.958 ± 0.024** (5-seed CV) | Ổn định (4/5 <1, var thấp); ratio <1 ở MỌI horizon 1–10 | Model chính của đề tài |
| LeWM (end-to-end pixel JEPA, ~22M) | 0.97 ± 0.15 (5-fold) | Biên, KHÔNG ổn (2/5 fold fail); ratio ≥1 ở horizon dài | Baseline |

- **`rollout1_ratio` = MSE_model / MSE_identity**. <1 = model giỏi hơn baseline "đoán frame sau y nguyên". Đây là chỉ số quyết định (val_pred đơn lẻ gây hiểu lầm — xem dưới).
- **Quy trình đã chạy (tự động):** k-fold LeWM fs5 (5-fold) → sweep 7 config (emb_dim/λ/frame_skip) → emb64 k-fold (worse) → chốt **LeWM base = fs5/emb256/λ0.1**. Rồi **encode 52,613 frame qua V-JEPA 2.1 ViT-L** (torch.hub, single-frame→(N,1024), `data/latents/` 208MB) → train `vjepa_ac` (1s/epoch) + 5-seed CV.
- **Bài học data/train quan trọng:**
  - **frame_skip=1 (10fps) HỎNG** LeWM: frame liên tiếp gần giống hệt → model học identity (ratio 1.25). Phải `frame_skip=5` (~0.5s/bước). vjepa_ac dùng frame liên tiếp (latent V-JEPA đổi rõ hơn nên OK).
  - **val_pred lừa người:** λ=0.05 có val thấp nhất nhưng latent collapse + bỏ qua action → vô dụng. Luôn xem **rollout-vs-identity + action-sensitivity**, đừng tin val_pred.
  - **eff_rank LeWM chỉ ~7-9/256** → data ít đa dạng (ga gần cố định) là giới hạn chính. Cần mẻ data ga-biến-thiên (xem `DATA_COLLECTION.md`).
- **Checkpoints (gitignored):** `checkpoints/vjepa_ac/best.pt` (AC predictor), `checkpoints/leworldmodel/fold{0..4}/best.pt` (LeWM), `checkpoints/vjepa2/…_384.pt` (encoder 4.8GB). **wandb:** project `lewm-rccar` (groups `lewm_fs5_kfold5`, `lewm_sweep`, `lewm_emb64_kfold3`, `vjepa_ac`).
- **Pipeline V-JEPA 2.1 (MỚI, chạy được):** `engine/encode.py` (torch.hub `vjepa2_1_vit_large_384` — **2.1 chỉ có trên torch.hub, KHÔNG trên HF**; HF id cũ trong doc là 2.0), `data/dataset.py::LatentTransitionDataset`, `engine/train.py` (AC trainer). Lệnh: `scripts/encode_dataset.py` rồi `scripts/train.py --config configs/train/vjepa_ac.yaml configs/model/vjepa_ac.yaml`.
- **CHƯA làm (Phase 4):** planning/CEM + closed-loop trên xe (mới là "tự lái"). Model chỉ mới là predictor.

## ⚠️ Việc phiên này (2026-06-07) — TÁI CẤU TRÚC REPO + LeWorldModel

**1. Repo reorganized (chuẩn AI-research).** Tách 2 subsystem:
- **ML package** `src/jepa_wm/` (cài `pip install -e .`): `models/` (encoders/vjepa, ac_predictor,
  **leworldmodel**, baselines), `data/` (dataset, sync), `engine/` (train, train_lewm, encode, losses),
  `planning/cem`, `utils/config`. Entrypoint ở `scripts/`; config YAML ở `configs/`.
- **Robot rig** `robot/`: gom hết `firmware/ android/ keys/ setup/ capture/(recorder,capture,controller)
  tools/ scripts/wfb_up.sh docs/(hardware) runcam.sdp test.py`.
- Docs dự án (PLAN/HANDOFF/DATA_COLLECTION/LeWorldModel) ở `docs/`. Bảng map old→new ở đầu `CLAUDE.md`.
- Xoá rác `package.json/package-lock.json`; thêm `pyproject.toml`, `README.md`.

**2. LeWorldModel (LeWM) — implement + ĐANG TRAIN.** Đọc paper `docs/LeWorldModel.pdf` → tóm tắt
`docs/LeWorldModel.md`. LeWM = **JEPA end-to-end từ pixel** (encoder ViT-Tiny tự train + predictor AdaLN +
**SIGReg** anti-collapse), **KHÔNG dùng V-JEPA** → là model độc lập / baseline mạnh, KHÁC `vjepa_ac`.
Port trung thực từ `github.com/lucas-maes/le-wm`. Train: `scripts/train_lewm.py` (chạy nền 2026-06-07,
batch 96, 224px, λ=0.1, early-stop patience 15). Checkpoint `checkpoints/leworldmodel/{best,last}.pt`,
log `runs/`. **Sớm: val pred 0.34→0.038 sau 8 epoch, rollout@1 tốt.** ⚠️ **eff-rank latent ~6-7/256**
(std≈1) → SIGReg chặn collapse tầm thường nhưng latent dồn ~6-7 chiều — nghi do data ít đa dạng
(ga gần hằng), đúng hạn chế SIGReg trên môi trường đơn giản. Theo dõi / cân nhắc emb_dim nhỏ hơn + data đa dạng.

**3. Data curated.** Theo keep-list của user: xoá **6 session rác** (cả local `data/raw/` lẫn Drive
`gdrive:JEPA/raw`) → còn **28 session / 53,151 frame**, tất cả đã `actions_synced.csv`. `JUNK` trong
`sync.py` để rỗng (curate bằng việc có-mặt-trên-đĩa). **28 video overlay** ở `data/videos/`.

## Dự án 1 dòng
Action-Conditioned World Model cho xe RC dựa trên **V-JEPA 2.1** (encoder ViT-L đóng băng, chỉ train AC
Predictor ~5M, CEM planning). Thu data bằng **điện thoại Android đặt trên xe**. Deadline **2026-06-15**.

## Trạng thái phase
- **Phase 1 (hạ tầng):** ✅ firmware ESP32, ESP-NOW LR.
- **Phase 2 (data):** ✅ app onboard (đầy đủ) + `src/sync.py` xong. ⏳ còn `offline_encode.py` (cần weights).
- **Phase 3 (training):** 🔄 **LeWorldModel đang train** (pixel JEPA from-scratch, baseline độc lập). `vjepa_ac` ⏳ chưa (chờ encode V-JEPA latents).
- **Phase 4 (planning):** ⏳ chưa (`cem_planner.py`, `inference_loop.py`; `controller.py` còn UDP cũ).

## Việc phiên này (2026-06-06, đợt 2) — servo + firmware + protocol thu data
**Phần cứng / lái:**
- **Đổi servo lái: KDS N680 HV → TowerPro MG946R** (analog, **≤6V — KHÔNG HV**). Servo cũ yếu/lỗi → giật/khựng
  khi đánh lái có tải; thay là hết. ⚠️ BEC phải **≤6V** cho MG946R (đừng 7.4/8.4V như lúc test con cũ → cháy).
- Vụ giật còn hé lộ **breadboard không tải nổi dòng đỉnh servo** — MG946R dòng thấp hơn nên *che* được, nhưng
  vẫn nên đưa **nguồn servo OFF breadboard + star-ground**.
- **Đi dây nguồn (đã chốt):** receiver FS-iA10B **chung nguồn BEC 6V** + **GND chung qua receiver** = OK (chuẩn RC,
  MG946R 6V không HV). Đường dòng-lớn (BEC↔servo) đi đầu-cắm/PCB chứ KHÔNG breadboard; **GND của ESP32 phải chạm
  mass chung** (qua dây GND cáp i-BUS). Bonus: receiver ăn BEC → ESP32 khỏi cấp 5V → hết lo back-feed VBUS phone.
- **Calibrate servo mới** (tool JOG: `firmware/src/servo_calibrate.cpp` + `env:servocal`): cơ khí
  **L1120 / R≥2000 / C1500 (thẳng, lệch +0)** → clamp firmware **`[1150,1850]` GIỮ NGUYÊN** (nằm gọn trong biên,
  khớp 29 session cũ). Chi tiết `firmware/specs.md`. ESC đính chính = **QuicRun 8BL150 bản thường (không WP)**.

**Firmware (`firmware/src/main.cpp`, build OK):**
- Gate ESP-NOW telemetry sau `TELEM_VIA_ESPNOW` (mặc định 0 — bỏ phát thừa tới dongle đã rút). Đường phone USB không đổi.
- ⚠️ **Bài học:** đã thử thêm guard `availableForWrite()` quanh `Serial.write` → **gây NO TELEM trên phone**
  (HWCDC trả availableForWrite=0 tới khi "connected"; usb-serial-for-android mở cổng không bắt tay DTR → guard bỏ
  qua mọi write). **Đã revert — ĐỪNG thêm lại.**

**Thu data:**
- **Dual rate throttle 7-8% → 14-15%** (mở dải ga trên sàn stall ~6%). KHÔNG phá data cũ (action→ESC độc lập
  dual rate, chỉ mở rộng tầm). **Cố định trim/EPA/dual-rate từ giờ.**
- **`DATA_COLLECTION.md` (mới)** — 5 kịch bản thu data ga-biến-thiên + decorrelation + tiêu chí dừng (histogram).

## Việc phiên này (2026-06-06) — app pass lớn + data pipeline
**App Android nâng cấp mạnh (build + cài + chạy OK trên A42):**
- **Fix δ_cam** ([MainActivity.kt](android/app/src/main/java/com/jepa/recorder/MainActivity.kt)+[SessionWriter.kt](android/app/src/main/java/com/jepa/recorder/SessionWriter.kt)):
  frame `t_ms` giờ = **mốc phơi sáng sensor** (`callback − dcam`), thêm cột `dcam_ms` vào `actions.csv`.
  **Đo được δ_cam ≈ 100ms** (A42 `SENSOR_INFO_TIMESTAMP_SOURCE=REALTIME`, ổn định ~98–103ms cả trong nhà
  lẫn ngoài trời). → data MỚI hết δ_cam; data CŨ trừ 100ms khi sync.
- **Quản lý + xem lại session** (`SessionListActivity`/`SessionPlayerActivity`/`SessionStore`/`SessionAdapter`):
  nút "📁 Sessions" → list + playback (overlay steer/throttle) + **xoá / đổi nhãn(meta.json) / xem info**.
- **Upload Google Drive** ([DriveUploader.kt](android/app/src/main/java/com/jepa/recorder/DriveUploader.kt),
  GoogleSignIn scope `drive.file` + OkHttp resumable, folder "JEPA", marker `.drive_uploaded`). **Cần setup
  OAuth 1 lần** — xem [android/DRIVE_SETUP.md](android/DRIVE_SETUP.md) (SHA-1 debug đã ghi sẵn).
- **🌙 Dim** (làm tối đen AMOLED, vẫn ghi — tiết kiệm pin).

**Data pipeline:**
- **`src/sync.py`** ✅ — re-pair mỗi frame bằng nội suy `telemetry.csv` 50Hz tại **thời điểm cảnh thật**
  (cũ: trừ δ_cam 100ms; mới: offset 0 vì có cột `dcam_ms`). Xuất `actions_synced.csv` **và** `imu_synced.csv`
  (gyro/accel/rotvec nội suy tại `t_scene_ms`). Loại frame ngoài khoảng/gap>60ms/mode≠1, bỏ session rác.
- **`tools/make_video.py`** — frames + actions → MP4 overlay steer/throttle/mode/δ (để inspect).
- **`tools/pull_drive.py`** — kéo zip từ Drive về (rclone).

## Data — hiện trạng (trong `data/raw/`, gitignored)
- **28 session** (sau khi curate theo keep-list user 2026-06-07, xoá 6 rác cả local+Drive) =
  **53,151 frame**, **tất cả đã có `actions_synced.csv`**. Backup Drive `gdrive:JEPA/raw` cũng = 28.
- Mỗi session usable có: `frames/*.jpg` (640×360), `telemetry.csv` (50Hz), **`actions_synced.csv`** (DÙNG cái
  này: frame_idx,t_scene_ms,steering,throttle,mode), **`imu_synced.csv`** (gx,gy,gz,ax,ay,az,rx,ry,rz),
  + IMU thô + gps + meta.json. **`actions.csv` là gốc lệch giờ — bỏ.**
- **Steering** đủ dải −1..1 (tốt); **throttle ~hằng** (29 session cũ pinned ~7.5%) → world model hiện ≈ steering-only.
  → **việc thu tiếp: mẻ data GA BIẾN THIÊN** theo **`DATA_COLLECTION.md`** (dual rate giờ 14-15%, servo mới đã calib).
- Backup Drive: `rclone copy data/raw gdrive:JEPA/raw` (remote `gdrive:` đã cấu hình; folder nhiều file nhỏ
  nên up chậm/vài giờ, resumable). Bạn của user đang thử data này.

## Lấy / xử lý data (lệnh hay dùng)
```bash
# Build + cài app (JDK21 snap android-studio + gradle-8.13; KHÔNG có gradlew trong repo)
JAVA_HOME=/snap/android-studio/current/jbr ~/.gradle/wrapper/dists/gradle-8.13-bin/*/gradle-8.13/bin/gradle \
  -p android assembleDebug
/home/pc5070ti/Android/Sdk/platform-tools/adb install -r android/app/build/outputs/apk/debug/app-debug.apk
# Lấy data: adb pull, hoặc MTP (gvfs), hoặc rclone từ Drive
python scripts/sync_dataset.py        # → actions_synced.csv + imu_synced.csv mỗi session
python robot/tools/make_video.py data/raw/session_XXXX   # video kiểm tra
rclone copy data/raw gdrive:JEPA/raw -P            # đẩy lên Drive
```

## Train / theo dõi LeWorldModel

```bash
pip install -e .                                   # cài package jepa_wm (1 lần)
PYTHONPATH=src python scripts/train_lewm.py \
  --config configs/train/lewm.yaml configs/model/leworldmodel.yaml
tail -f /tmp/lewm_train.log                         # log epoch
tensorboard --logdir runs                           # http://localhost:6006
# checkpoint: checkpoints/leworldmodel/{best,last}.pt
```

## Gotcha
- **Cài lại app**: keystore debug máy này (pc5070ti, SHA-1 `B3:FA:22:..:3C:3D`) ≠ keystore APK cũ (máy khác)
  → `INSTALL_FAILED_UPDATE_INCOMPATIBLE` → phải `adb pull` hết session **TRƯỚC** rồi `adb uninstall` + cài lại
  (gỡ app XOÁ `Android/data/.../sessions`). Đã backup đủ 34 session về `data/raw/` rồi.
- **Cắm phone vào ESP32 = cổng NATIVE (303A); nạp firmware = cổng CH343.** Đừng cấp 5V ngoài khi đang cắm phone.
- **Servo = MG946R (analog, ≤6V — KHÔNG HV).** BEC phải ≤6V (đừng 7.4/8.4V → cháy). Clamp [1150,1850], calib `firmware/specs.md`.
- **NO TELEM nhưng "USB OK"** = thường do firmware không phát ra cổng native (đang chạy `env:servocal`?) hoặc guard chặn write — KHÔNG dùng `availableForWrite()` chặn `Serial.write` (xem đợt 2).
- `data/` + `android/app/build/` đều gitignored.

## Bước tiếp theo gợi ý (cập nhật 2026-06-07)
1. **🎯 ĐANG LÀM: thu mẻ data mới trong CÔNG VIÊN** theo **`docs/DATA_COLLECTION.md`** (đã viết lại cụ thể:
   số đo gap throttle, ràng buộc công viên, 5 kịch bản, kế hoạch ~16–20 session, tiêu chí dừng). Trọng tâm:
   **biến thiên ga/tốc độ + đa dạng cảnh** (steering đã đủ; eff_rank ~8 chứng tỏ data đơn điệu là bottleneck).
2. **Sau khi thu:** `scripts/sync_dataset.py` → `scripts/encode_dataset.py` (chỉ encode buổi mới) →
   train lại `scripts/train.py` (vjepa_ac) + `scripts/train_lewm.py`. Kiểm coverage bằng phần report trong
   `scripts/eval_lewm.py`. Kỳ vọng: eff_rank ↑, rollout1_ratio ↓.
3. **Phase 4 — planning (mới là "tự lái"):** `src/jepa_wm/planning/cem.py` (CEM đã có stub) + closed-loop
   trên xe (phone TCP-stream frame → PC chạy vjepa_ac+CEM → 2-byte action → ESP32). `robot/capture/controller.py`
   còn map UDP cũ → sửa sang dongle/native serial + throttle Mode-3 linear (xem CLAUDE.md mục controller).
4. (Tùy chọn) chuẩn hóa action per-dim theo biên thực; cân scale throttle cho cân với steering.
