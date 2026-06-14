> # ⚠️ ĐÍNH CHÍNH (2026-06-14 CHIỀU đợt 2) — KẾT LUẬN "OOD" DƯỚI ĐÂY ĐÃ SAI/NHIỄU
> **Đọc `docs/HANDOFF.md` section đầu trước.** Toàn bộ §8b ("OOD XÁC NHẬN") so **xe-chạy (in-domain
> 0.413)** với **xe-ĐỨNG (bãi ~0.02)** = so táo-cam. Sự thật đo lại:
> - Ép `speed=0` trên CHÍNH VAL train → contrast tụt 0.413 → **0.107/0.300** mà KHÔNG đổi cảnh.
> - Live **cold tại park này**: ga≥0.07 → contrast **0.2–0.57** (vượt 0.41); chỉ phẳng khi ga<0.06.
> - ⇒ **KHÔNG OOD.** Phẳng = regime ĐỨNG YÊN (dynamics `yaw=k_yaw·steer·speed`→0). Gốc thật =
>   **deadlock đứng yên** (hộp ga đè vùng chết <0.06); fix = sàn ga `TMIN=0.07`. Tường kế = **ánh sáng**.
> - §8b/§5 H2 bên dưới GIỮ làm lịch sử nhưng **đừng trích "OOD" làm kết luận.**

# CEM KHÔNG TẠO ĐƯỢC TÍN HIỆU LÁI — chẩn đoán bằng `--step` energy landscape (2026-06-14 TRƯA, bãi)

> **Mục đích file:** lưu ĐẦY ĐỦ phát hiện + log thật của buổi probe `--step` ở công viên 06-14 trưa,
> để session/máy sau tiếp tục **phân tích nguyên nhân vì sao CEM không biết lái**. Đây là lần đầu
> soi TRỰC TIẾP energy landscape L1 của CEM trên xe thật (không phải suy từ hành vi). Nền:
> [HANDOFF.md](HANDOFF.md), [CLOSED_LOOP_FAILURE.md](CLOSED_LOOP_FAILURE.md).

## TL;DR (đọc cái này trước)

Lột bỏ HẾT lớp phụ trợ (geosteer/HOLD/off-route/GPS/floor/cruise/kick/EMA/kickstart-clamp) → chạy
**CEM thuần visual** + `--step` (mỗi nhịp DỪNG, in landscape `E(steer)`/`E(throt)`). Kết quả trên
route `test_di_thang` (thẳng, 6 subgoal tay, teach cùng buổi):

1. **`contrast` của E(steer) ~0.02–0.11 ở MỌI nhịp** (mốc in-domain ban ngày ≈ **0.45**) → landscape
   **phẳng gấp ~10–20 lần mức tin được**. Model **không phân biệt nổi lái trái/phải**.
2. **Phẳng NGAY CẢ khi cos cao** (seq79 cos **+0.604** vẫn contrast 0.023; seq53 ở run trước cos
   **+0.658** contrast 0.026). → KHÔNG phải cos-dropout (mất khớp ảnh). Model dở phân biệt lái **dù
   view khớp target**.
3. **Hình E(steer) = chữ-U-NGƯỢC / RAMP, KHÔNG phải lòng chảo** → đáy luôn ở **CỰC (đáy@ ±1.00)**.
   Tức model cho **lái thẳng (center) là TỆ NHẤT**, full-lock là "tốt nhất" — trên route ĐI THẲNG
   thì NGƯỢC hoàn toàn (đáng lẽ center mới đúng). → tín hiệu **thoái hoá / OOD** rõ rệt.
4. **CEM ra full-lock ±0.8–1.0 mọi nhịp**, cả **CÓ** lẫn **KHÔNG** warm-start (policy). Warm-start
   **KHÔNG cứu** (giả thuyết "warm-start kéo về thẳng" đã bị BÁC bằng log).
5. **Throttle KHÁC NHAU theo warm-start (đính chính — quan trọng):**
   - **Cold CEM (`POLICY=`) ra ga 0.05–0.10 BÌNH THƯỜNG → xe TIẾN TỐT** (xác nhận bởi user: lần step
     ĐẦU TIÊN cold, xe chạy + ga bình thường). Log run B: ga `+0.055, +0.100, +0.098, +0.054, +0.090, +0.065`.
   - **Warm-start + kickstart-clamp TẮT → ga SỤP về ~0** (`0.000, 0.002, 0.000…`) → xe đứng. Nguyên
     nhân: BC policy đề xuất ga~0 (standstill-attractor), warm-start σ nhỏ + bỏ clamp → CEM kẹt ở ~0.
   - ⇒ **throttle KHÔNG phải vấn đề gốc** (cold CEM ra ga ổn, xe chạy). Kickstart-clamp tồn tại CHÍNH
     vì lý do này — tắt nó LỘ ra điểm yếu của warm-start path. **Vấn đề gốc DUY NHẤT = STEERING** (1–4).
   - (⚠ mình từng claim sai "model luôn ra ga ~0" do lấy nhầm số của run warm-start — ĐÃ sửa.)

**⇒ Kết luận:** trên route này **world-model KHÔNG sinh được tín hiệu LÁI dùng được** (throttle ổn khi
cold CEM). Không phải lỗi
config/warm-start/subgoal-spacing. Đây là **giới hạn model** (đúng negative-finding HANDOFF/CLOSED_LOOP_FAILURE),
giờ **chứng minh bằng mắt** qua landscape. Hai nghi can chính: **route thẳng tự-giống = ca tệ nhất**
(bẻ lái gần như không đổi cảnh dự đoán) + **OOD** (cảnh park khác data train).

**✅ ĐÃ PHÂN ĐỊNH (offline, §8b):** chạy `probe_energy.py` trên VAL data train (CÙNG scoring) →
**contrast in-domain = 0.413, sign-đúng 96%, argminE khớp người lái trong 0.06**. Bãi ~0.02 = **thấp
20×**. ⇒ **OOD XÁC NHẬN: model LÀNH, cảnh park 06-14 ngoài phân bố train.** "CEM không biết lái" =
generalization gap, KHÔNG phải bug. Việc chính = giải OOD (fine-tune data park / recovery / 3DGS sim),
không phải knob bãi. (Chi tiết §8b, §8.)

---

## 1. Config đã chạy (đã commit trong `run_infer.sh` + `scripts/inference_loop.py` phiên này)

Buổi này strip dần `run_infer.sh` về **CEM trần** để soi model không bị lớp nào che. Các knob mới (env):

| Đổi | Cờ | Ý nghĩa |
|-----|-----|---------|
| Thuần visual, bỏ GPS | `--graph none` → `car_xy=None` | pop subgoal CHỈ bằng cosine; nhánh pop-GPS chết |
| Floor tắt | `--floor-no-gps` + `CRUISE=0` + `KICK=0` | ga = thuần CEM trong `[TMIN,THR]`, không sàn ép |
| Lái trần | `SMOOTH=0` | `steer = raw_steer` (bỏ EMA) |
| Kickstart-clamp tắt | `--no-kickstart-clamp` (FLAG MỚI) | không ép ga-init warm-start ≥0.75·cap khi đứng |
| HOLD tắt | `LOCK=0` | không đóng băng lái khi cos sập |
| A/B warm-start | `POLICY=` (rỗng=tắt) / mặc định `policy_prior_cd4` | bật/tắt seed CEM |
| pop reach | `REACHCOS=0.6` (mặc định, was 0.80) | ngưỡng Luật-1 pop |
| ga band | `TMIN`/`THR` (mặc định [0,0.10]) | CEM tự chọn ga trong dải |
| step timeout fix | STEP → `--manual-timeout-s 0` | **bug đã vá**: 60s timeout đếm giờ thật khi đang đọc step → tự DỪNG oan |
| OOM horizon | `--score-chunk` (FLAG MỚI), env `CHUNK` | chấm CEM theo chunk → HOR 6-8 không vỡ 16GB |

Lệnh probe: `STEP=1 [POLICY=] [HOR=n] [CHUNK=64] bash run_infer.sh` → web ▶ Run route → mỗi nhịp ENTER/`s`/`q`.

**Đọc landscape:** `contrast=(Emax−Emin)/Emin`; ≥0.15 = đáy tin được, ~0 = phẳng = ĐOÁN. `đáy@`=
action có E thấp nhất; `model@`=CEM chọn. Cột `▁..█`: thấp `▁`=E thấp=model thích.

## 2. LOG THẬT — run A: CÓ warm-start (`STEP=1 bash run_infer.sh`, HOR=4), route test_di_thang

```
[step] seq79  cos +0.604  manual 1/6
  model steer +1.00 ga +0.022  → ÁP steer +0.96 ga +0.022
  E(steer) -1[▁▂▃▅▅▆▆▇▇▇█▆▆▅▅▅▄▄▃▃▂]+1  đáy@-1.00 model@+1.00 contrast 0.023  ⚠PHẲNG
  E(throt) 0.00[▁▁▁▁▂▆█]0.10  đáy@+0.050 contrast 0.096
[step] seq239 cos +0.465  manual 2/6
  model steer +0.13 ga +0.028  → ÁP +0.09
  E(steer) -1[▃▄▅▆▇▇▇▇█▇▇▅▅▄▄▄▃▃▂▂▁]+1  đáy@+1.00 model@+0.13 contrast 0.021  ⚠PHẲNG
  E(throt) 0.00[█▇▄▁▁▅▃]0.10  đáy@+0.050 contrast 0.017
[step] seq372 cos +0.428  model steer -0.74 ga +0.038
  E(steer) -1[▂▄▅▆▆▆▆▆▇▇█▆▅▅▅▄▄▄▃▂▁]+1  đáy@+1.00 model@-0.74 contrast 0.019  ⚠PHẲNG
[step] seq459 cos +0.487  model steer -0.44 ga +0.000
  E(steer) -1[▄▅▆▇█▇▇▇▇▇▆▄▃▂▂▂▂▂▂▁▁]+1  đáy@+1.00 model@-0.44 contrast 0.028  ⚠PHẲNG
[step] seq528 cos +0.500  model steer +1.00 ga +0.028
  E(steer) -1[▂▄▆▇▇█▇▇▇▇▇▅▄▄▄▄▄▃▃▂▁]+1  đáy@+1.00 model@+1.00 contrast 0.020  ⚠PHẲNG
[step] seq599 cos +0.476  model steer +1.00 ga +0.002
  E(steer) -1[▁▂▃▃▄▅▆▇▇▇█▇▆▆▆▅▅▅▄▄▃]+1  đáy@-1.00 model@+1.00 contrast 0.024  ⚠PHẲNG
[step] seq657 cos +0.443  model steer +0.80 ga +0.001  đáy@-1.00 contrast 0.026  ⚠PHẲNG
[step] seq714 cos +0.517  model steer +1.00 ga +0.000  đáy@-1.00 contrast 0.023  ⚠PHẲNG
[step] seq827 cos +0.564  model steer +0.87 ga +0.000  đáy@-1.00 contrast 0.026  ⚠PHẲNG
```
→ `model@` ∈ {+1.00, +0.13, −0.74, −0.44, +1.00, +1.00, +0.80, +1.00, +0.87} = full-lock đảo dấu loạn.
`ga model` tụt dần về 0.000. Warm-start (policy_prior_cd4) KHÔNG anchor về thẳng.

## 3. LOG THẬT — run B: KHÔNG warm-start (`STEP=1 POLICY= bash run_infer.sh`, HOR=4)

```
[step] seq53  cos +0.658  manual 1/6  model steer +0.01 ga +0.055 → ÁP -0.03
  E(steer) -1[▁▂▃▄▄▄▄▃▃▄▇▇█▇▇▆▆▆▆▆▅]+1  đáy@-1.00 model@+0.01 contrast 0.026  ⚠PHẲNG
[step] seq320 cos +0.502  model steer +0.91 ga +0.100
  E(steer) -1[▇█▇▇▇▇▆▅▄▂▁▁▁▂▂▃▃▃▃▃▃]+1  đáy@+0.10 model@+0.91 contrast 0.090  ⚠PHẲNG
[step] seq477 cos +0.290  model steer +0.27 ga +0.098
  E(steer) -1[▁▁▁▁▁▁▁▁▁▁▃▄▅▆▆▇▇▇▇▇█]+1  đáy@-1.00 model@+0.27 contrast 0.087  ⚠PHẲNG
[step] seq597 cos +0.367  model steer +0.96 ga +0.054
  E(steer) -1[▁▁▂▃▄▄▄▄▃▃▅▅▄▄▄▅▅▆▆▇█]+1  đáy@-1.00 model@+0.96 contrast 0.022  ⚠PHẲNG
[step] seq678 cos +0.302  model steer -0.27 ga +0.090  (sau khi 's' nhìn lại frame mới)
  E(steer) -1[▁▁▁▂▂▂▁▁▁▃▆▆▇▇▇▇▇▇▇▇█]+1  đáy@-1.00 model@-0.27 contrast 0.107  ⚠PHẲNG
[step] seq787 cos +0.329  model steer +0.73 ga +0.065  đáy@-1.00 contrast 0.077  ⚠PHẲNG
   → [web] ⏱ subgoal 2/6 quá 60s (cos 0.315) DỪNG   ← BUG timeout-đếm-khi-step, ĐÃ VÁ
```
→ cold CEM cũng full-lock; seq53 tình cờ ra +0.01 (thẳng, đúng) rồi pop sg1→2, sau đó loạn.

## 4. Quan sát chìa khoá để session sau phân tích

1. **contrast bất biến ~0.02–0.11** bất kể cos (0.29→0.66), bất kể warm-start. → không phải knob.
2. **Hình landscape = đỉnh-ở-giữa (U-ngược) hoặc ramp** → minimum ở cực. Model **ghét center**. Trên
   route thẳng center MỚI đúng → model **đảo ngược** so với sự thật vật lý → nghi OOD nặng.
3. **E(throt) cũng phẳng** (contrast 0.02–0.10); `đáy@` nhảy 0.0/0.05/0.10; CEM chọn ga ~0.
4. **cos centered ~0.29–0.66** (subgoal kề ~0.6, xa ~0.3) — pop Luật-1 (reach 0.6) chỉ chớm đạt ở
   subgoal đầu; chủ yếu pop bằng Luật-2 (near+next-closer). Thang cos OK, **không phải vấn đề cos**.

## 5. Giả thuyết nguyên nhân (chưa phân định — việc của session sau)

| # | Giả thuyết | Cách kiểm |
|---|-----------|-----------|
| H1 | **Route thẳng tự-giống** = bẻ lái không đổi cảnh dự đoán → landscape suy biến (ca tệ nhất) | teach route CÓ CUA rõ → contrast ở cua tăng? |
| H2 | **OOD** — cảnh park 06-14 khác phân bố train (ánh sáng/scene/domain) → predictor thoái hoá → U-ngược | thử trên frames CÓ trong train-set (replay offline `eval_goal_reaching_ac`) — contrast ở data train có cao 0.45 không? Nếu offline cao mà bãi thấp → OOD |
| H3 | **Tầm dự đoán ngắn** (HOR4×0.22s×ga~0.05 → dịch dự đoán <0.5m < target lookahead) → mọi action ~ nhau | `STEP=1 HOR=6 CHUNK=64` → contrast tăng? (đã wire score-chunk, OOM đã fix) |
| H4 | ~~ga~0 → xe đứng trong dự đoán → steer vô nghĩa (artifact probe ga thấp)~~ | **ĐÃ BÁC** ↓ |

**Ghi chú H4 — ĐÃ BÁC bằng run cold:** code `--step` quét E(steer) ở `ga = max(abs(throt), 0.02)`.
Trong run COLD, `throt`(model) = **0.05–0.10** → probe đã quét steer ở ga 0.05–0.10 (xe THỰC SỰ tiến
trong dự đoán) mà landscape **VẪN phẳng** (contrast 0.022–0.107). ⇒ phẳng KHÔNG phải artifact ga thấp;
model genuinely không phân biệt lái dù có throttle. Loại H4 → dồn nghi vào **H1 (route thẳng tự-giống)
+ H2 (OOD)**. (Chỉ run warm-start mới có ga~0, nhưng steer của nó cũng full-lock y hệt → không đổi kết luận.)

## 6. Đính chính dữ liệu (đã lưu memory `throttle-data-not-zero`)

Throttle data train (`raw_mixed`, 228.511 frame): **median +0.084**, 87% frame có ga thật, chỉ 12.7%
~0. ⇒ "data ga ~0 nên model học ga 0" là SAI. Model LẼ RA tự ra ~0.08; việc nó ra ~0 lúc inference
là **triệu chứng OOD/thoái hoá**, không phải do data. (Đừng lặp claim sai này.)

## 7. Artifacts trên đĩa (máy pc5070ti, `logs/` gitignored — KHÔNG theo repo)

- Run bundles (config.json + frames/<seq>.jpg + run.jsonl per-tick): `logs/run_20260614_120916`
  (run B cold POLICY=), `logs/run_20260614_121707` (run A warm-start). Frame-level + steer/raw/throt/cos.
- stdout đầy đủ: `logs/infer_20260614_120908.log` (B), `logs/infer_20260614_121659.log` (A).
- ⚠ Máy khác KHÔNG có các file này (gitignored) — log cốt lõi đã NHÚNG trong §2/§3 file này.

## 8b. ✅ KẾT QUẢ OFFLINE (chạy ngay 06-14) — **OOD XÁC NHẬN, model LÀNH**

Chạy `scripts/probe_energy.py` (CÙNG `planner.score` + CÙNG công thức contrast của `--step`, nhưng
trên **VAL window data train** in-domain ban ngày, d=4 khớp HOR park, grid 21):

```
PYTHONPATH=src python scripts/probe_energy.py --checkpoint checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt -d 4 --n-windows 300
→ 300 window: median |argminE − teacher| = 0.058 | sign-đúng khi quẹo (|tea|>0.15): 98/102 | median contrast = 0.413
```

| Chỉ số | IN-DOMAIN (VAL train) | BÃI park 06-14 (`--step`) | Tỉ lệ |
|--------|----------------------|---------------------------|-------|
| **median contrast E(steer)** | **0.413** | **~0.02–0.11** | **~20× thấp hơn ở bãi** |
| argminE vs teacher (lệch) | 0.058 (rất khớp) | đáy ở CỰC ±1.0 (vô nghĩa) | — |
| sign-đúng khi quẹo | **98/102 (96%)** | ~ngẫu nhiên | — |

(Bản `--turn-only` 200 window CHỈ lúc quẹo: **contrast 0.335, sign 191/200 (95.5%)**, argminE lệch 0.139
— in-domain model phân biệt lái TỐT ngay cả riêng các khúc cua → loại trừ "model dở ở cua".)

→ **Model + CEM HOÀN TOÀN LÀNH trên data train**: landscape có **lòng chảo thật** (contrast 0.41),
đáy lái **khớp người lái trong 0.06**, **đúng dấu 96%** lúc quẹo. Vậy **landscape phẳng ở bãi KHÔNG
phải model hỏng** — mà là **OOD: cảnh park 06-14 nằm ngoài phân bố train** → predictor thoái hoá →
energy phẳng → CEM không bám được.

**⇒ CHỐT NGUYÊN NHÂN "CEM không biết lái" = OOD generalization gap, KHÔNG phải bug config/CEM/warm-start.**
World-model offline (đóng góp chính của paper) **vẫn vững** (đây chính là bằng chứng định lượng nó hoạt
động in-domain); gap nằm ở **khái quát hoá sang cảnh mới**. Đây là negative-finding TRUNG THỰC, đo được.

## 8. Việc tiếp (ưu tiên) — H4 đã bác, H2(OOD) ✅ XÁC NHẬN, còn H1

1. ~~H2 (OOD) offline~~ → **✅ ĐÃ LÀM (§8b): OOD XÁC NHẬN** (in-domain contrast 0.413 vs bãi ~0.02).
2. **GIẢI OOD = việc chính giờ** (không phải knob bãi): (a) **thu data Ở CHÍNH công viên này** rồi
   fine-tune predictor (rẻ nhất, đúng domain); (b) **recovery-data augmentation** (CLOSED_LOOP_FAILURE §8);
   (c) **3DGS sim** từ data park để lặp closed-loop trong nhà (SIM_3DGS_PLAN.md). Cosmos-Transfer relight
   nếu gap là ánh sáng.
3. (phụ, xác nhận thêm) **H1 — route CÓ CUA** ở bãi: nếu contrast vẫn ~0.02 trên route quẹo → đóng
   đinh OOD theo chiều closed-loop; nhưng §8b đã đủ kết luận, H1 chỉ là cross-check.
4. (phụ) Warm-start path: ga sụp ~0 khi kickstart-clamp tắt — nếu muốn dùng warm-start, BẬT lại
   `--kickstart-clamp` (mặc định inference_loop = True; run_infer đang ép `--no-kickstart-clamp`).

**Lệnh re-probe (đã wire, OOM đã fix):**
```
STEP=1 POLICY= bash run_infer.sh           # cold CEM (ga bình thường, xe chạy) — baseline soi steer
STEP=1 HOR=6 CHUNK=64 bash run_infer.sh    # horizon dài, chống OOM (PHẢI có CHUNK!)
```
