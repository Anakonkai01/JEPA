# Closed-loop trên xe thật — phân tích đầy đủ (06-13) cho paper + bước sau

> **TL;DR:** Teach&repeat điều-hướng-bằng-subgoal-ảnh (V-JEPA-2.1-AC + CEM) **bám tuyến tốt nửa
> đầu route rồi BUNG ra lề** ở điểm "cos-dropout". Cơ chế (đo ~10 run, mọi config): tại một subgoal
> mà ảnh live không khớp ảnh teach → **cos<0.1 → CEM mất gradient → lái loạn full-lock đảo chiều →
> xe văng >2m → KHÔNG có tín hiệu kéo về → đâm lề.** Đây là **giới hạn model/data (no-recovery +
> panic tại cos-dropout)**, KHÔNG phải config — knob chỉ dời điểm bung, không xoá. World-model
> (đóng góp chính, offline 06-07) đứng vững độc lập.

## 1. Thiết lập
- Teach&repeat tay (kiểu ViNG): lái xe chụp chuỗi subgoal ảnh+GPS dọc tuyến → repeat: phone
  (frame+GPS+rotvec) → PC V-JEPA 2.1 ViT-L (đóng băng) → AC predictor `vjepa_ac_car_cd4` → CEM
  (samples×iters, horizon) lái tới subgoal patch tokens. Pop subgoal theo GPS (±visual-confirm).
  Recovery hình học `geosteer` (Stanley) — tùy chọn.
- Bãi cỏ công viên, tuyến ~thẳng ~15m. Routes: `parkfix3`(53sg), `park4_di_thang`(47), `park6_di_thang`
  (59 sau khi sửa, xem §5). Logs: `logs/infer_20260613_*.log`.

## 2. KẾT QUẢ: không run nào về đích; bung ở điểm cos-dropout
Run SẠCH cuối (pure-visual, tick 1.78s, không geosteer — `logs/infer_20260613_171912.log`):
- Giữ lệch-ngang (xt) **<0.5m từ sg1–6** (bám tuyến đẹp).
- **sg7: cos tụt 0.13→0.08→0.02.** sg8–9: CEM bung **raw steer +1.00 rồi −0.68/−0.86/−1.00**
  (đảo chiều full-lock) → veer trái → **xt 2.4m → đâm bụi cỏ.**
- **Yếu tố cộng hưởng:** `--kick-throttle` STEER-AWARE (×(1+0.5|steer|)) → lúc bung lái ±1.0, ga
  nhảy 0.06→0.12 → **xe tăng tốc TRONG lúc quẹo bậy** → đâm mạnh hơn.

Pattern qua các run (vị trí điểm-bung đổi theo run, cơ chế y hệt):

| Run | tick | config | bám tốt tới | bung tại (cos) | kết |
|---|---|---|---|---|---|
| 162029 | 1.15s | route 112 (bẩn, §5) | sg57 (d<1m) | — (seam) | STOP |
| 163607 | 1.13s | 59, fast, GEO0 | **sg18 (<0.5m)** | sg21 (cos0.07) | bung trái +3.2m |
| 163831 | 2.82s | 59, slow | sg8 | sg10 (cos0.27) | trôi −2.4m |
| 164827 | 2.90s | 59, slow | sg12 | sg27 | trôi trái +2.8m |
| 171022 | 2.82s | 59, geosteer ON | sg20 | sg23 | 🛑 GEOSTEER DIVERGE (rotvec hỏng) |
| 171912 | 1.78s | **59, pure-visual SẠCH** | sg6 | **sg7 (cos0.02)** | veer trái → bụi cỏ |

## 3. CHẨN — cơ chế bung (đo, không đoán)
**Vòng xoáy tại điểm cos-dropout:**
```
bám tuyến (cos>0.15)  →  tới subgoal "yếu" (live ≠ teach)  →  cos < 0.1
   ↑                                                              ↓
đâm lề  ←  no-recovery (văng >2m mất luôn)  ←  CEM lái loạn full-lock ±1  ←  mất gradient
                                                    ↓ (cộng hưởng)
                                          kick steer-aware nâng ga → tăng tốc khi quẹo bậy
```
- **Vì sao cos-dropout:** một số subgoal ảnh live (heading/ánh-sáng/vị-trí repeat khác teach) không
  khớp ảnh teach → centered-cos tụt <0.1. Embedding teach KHÔNG degenerate (đo §4) — dropout là do
  KHỚP LIVE, không phải teach xấu.
- **Vì sao panic:** CEM energy = ‖predicted_patch − goal_patch‖; cos thấp = goal không phân-biệt-được
  trong latent → energy phẳng theo steering → CEM chọn lái ~ngẫu nhiên, hay full-lock + đảo chiều.
- **Vì sao không cứu được:** teach chụp toàn bộ KHI XE Ở GIỮA tuyến → **không có ảnh teach nào dạy
  "lệch 2m thì bẻ về hướng nào"** → một khi văng ra, vision mù hướng-về (cos chỉ tụt, không chỉ đường).

## 4. Bằng chứng: KHÔNG phải "cảnh tự-giống / teach xấu"
- **Embedding teach tốt đều** (encode lại qua V-JEPA, đo độ phân-biệt): parkfix3 self-gap 0.070;
  parkfix_5 self-gap 0.094 (≈/hơn). RAW-cos giữa-sg ~0.98, centered-norm ~5. Các route phân-biệt-được
  như nhau. → sập KHÔNG do scene/teach.
- **Cos quality theo route khi CHẠY:** parkfix3 (sáng, chạy ngay sau teach) **66%>0.3**; parkfix_5
  (teach 14:11, chạy 14:50, nắng gắt) **0%>0.3**. → khớp-live nhạy với **alignment teach-vs-repeat
  (giờ/nắng/heading)**, không phải biểu diễn V-JEPA.
- Vì vậy bản đầu của doc này kết luận "bức tường tự-giống" là **SAI** — đã sửa.

## 5. BUG QUY TRÌNH đã phát hiện+vá (06-13)
- **Teach CỘNG DỒN:** `route_web.api_manual_snap` đọc meta cũ rồi `.append` — teach lại cùng tên
  **không xoá** → park6 từ 59→**112 subgoal** với **bước nhảy 29m ở giữa** (lượt 1 + lượt 2). Hệ quả:
  xe tới goal (cuối lượt 1) nhưng còn 53 subgoal "ma" của lượt 2 (bắt đầu cách 29m) → wp_idx kẹt →
  "đi qua goal mà không pop". **Đã vá:** `api_routes_delete` giờ `shutil.rmtree` cả thư mục ảnh/meta
  (xoá→teach lại cùng tên = sạch). **Đã cắt park6 về 59 (1 lượt).** ⚠️ Vẫn cần **restart route_web**
  để fix có hiệu lực; hoặc teach TÊN MỚI mỗi lần.
- **Knob `run_infer.sh`:** thêm env `SMP/ITERS/HOR/LOOK/SMOOTH/TRIM/GEO/POP/THR/KICK/GSH/GSDBG`
  (chỉnh không sửa file). **geosteer mặc định GEO=0** (rotvec hỏng, xem §6). Fix typo `mkdir lo5s→logs`.

## 6. Các đòn ĐÃ THỬ ở bãi (đều không về đích → xác nhận là tường, không phải config)
- **Tick:** 128/h6 (4.5s) → 48/h4 (1.1s). Nhanh giúp bám LÂU hơn (sg8→sg18) nhưng vẫn bung ở cos-dropout.
- **Lookahead** 0.5→2.0m (target xa = gradient lái mạnh hơn — giảm lật-dấu lúc cos tốt, không cứu dropout).
- **steer-smooth** 0.1→0.45 (dập lái sốc — output êm hơn nhưng raw vẫn ±1.0 ở dropout).
- **throttle** 0.08→0.06 (chậm — nhưng kick steer-aware vẫn nâng 0.12 lúc panic).
- **pop** GPS thuần (POP=0) — fix kẹt-pop, OK.
- **geosteer (rotvec heading):** `he` ±50–180° (calib rotvec↔graph hỏng, nghi handedness) → DIVERGE/flail.
  Thêm `--geosteer-gps-heading`(GSH) heading GPS-track + `--geosteer-debug` — **CHƯA test** (user dừng bãi).
  *(Lưu ý: geosteer = lái GPS-hình-học, user BÁC vì "vứt model" — chỉ là fallback, không phải hướng chính.)*

## 7. Đóng khung cho paper
1. **Claim chính:** đánh giá đầu tiên họ V-JEPA 2 trên robot di động (xe RC); world-model latent thắng
   baseline "đứng yên" — rollout@1/identity **0.958±0.024** (5-seed CV), action-sensitivity Δsteer 0.16,
   transfer chéo-domain-servo có lợi (số 06-07, offline rigorous, độc lập closed-loop).
2. **Closed-loop (kết quả trung thực):** teach&repeat bám tuyến nửa đầu (cos định-vị 50–66% tick trên
   route hợp light), nhưng **bung tại cos-dropout** do thiếu tín hiệu recovery → không về đích. Giới hạn
   ở tầng **nav-robustness + control**, KHÔNG ở representation.
3. **So Meta:** Meta test robot ARM (cảnh bàn cố định, action gây đổi cảnh LỚN+tức thì, KHÔNG có
   heading/lighting/lateral drift). Xe ngoài trời: action→đổi-cảnh nhỏ + cos-dropout + no-recovery →
   chế-độ khó hơn về robustness. ViNG/ViKiNG chạy được vì policy train TRÊN data có recovery (lệch→về).
4. **Negative finding có giá trị:** "Open-loop teach&repeat trên frozen video-encoder + CEM thiếu
   lateral-recovery → bung ở điểm visual-mismatch trên cảnh ngoài trời." Bảng §2 + cơ chế §3 là bằng chứng.

## 8. BƯỚC SAU (về nhà — KHÔNG phải knob ở bãi)
1. **Retrain có RECOVERY DATA (fix gốc):** thu/augment cảnh xe LỆCH khỏi tuyến rồi action kéo về
   (đúng cái ViNG/Meta có, data teach-1-lượt-giữa-line của mình THIẾU). → predictor/policy học hướng-về
   → hết panic ở cos-dropout. Cân nhắc: lái-tay đa dạng (lệch trái/phải rồi về) + label; hoặc augment
   từ data có sẵn.
2. **3DGS sim** (`docs/SIM_3DGS_PLAN.md`): dựng lại bãi từ data → test closed-loop trong nhà, lặp ban
   đêm, có kiểm soát heading/lighting → tách biến, lặp control nhanh không nắng/pin.
3. **(phụ) bỏ kick steer-aware khi |steer| lớn lúc cos thấp** (đừng tăng tốc khi đang panic) — giảm
   mức độ đâm, không cứu việc về đích.
4. **(phụ) test `GSH=1`** (geosteer heading GPS-track) — nếu chấp nhận fallback hình-học cho đoạn cos thấp.

## 9. Liên kết
- World-model số: `docs/HANDOFF.md` (06-07 "Đêm tự động"), `docs/VJEPA2_AC_CAR.md`.
- Sim: `docs/SIM_3DGS_PLAN.md`. Logs bằng chứng: `logs/infer_20260613_*.log` (route 59 sạch: 17xxxx).
- Code: `scripts/inference_loop.py` (geosteer flags + GSH/GSDBG), `scripts/route_web.py` (delete dọn meta),
  `run_infer.sh` (env knobs). Encode-discriminability + parse-log scripts: chạy trong session 06-13.
