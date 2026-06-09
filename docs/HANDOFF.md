# HANDOFF — đọc cái này trước khi tiếp tục

> Tóm tắt tình hình cho phiên sau. Cập nhật: **2026-06-09**.
> Nền đầy đủ: [../CLAUDE.md](../CLAUDE.md) · [../README.md](../README.md) · [PLAN.md](PLAN.md) ·
> [LeWorldModel.md](LeWorldModel.md) · [../robot/android/README.md](../robot/android/README.md) ·
> [../robot/android/DRIVE_SETUP.md](../robot/android/DRIVE_SETUP.md). Cập nhật file này mỗi khi trạng thái đổi.

## ▶️ VIỆC NGAY (2026-06-09 tối) — THỰC THI RETRAIN 384/P2 (đã chuẩn bị xong, CHƯA chạy)
**Data recovery (lạng→lùi→chỉnh) ĐÃ UP DRIVE đầy đủ.** Toàn bộ CODE retrain-prep đã commit+push
(`b4bb9e4`, đã smoke-test): 384px control, num_tokens 576, prev-action state (state_dim 12),
depth 12, inference gộp nav+control 1 encode, CEM `prev_action_idx`. Plan đầy đủ: `~/.claude/plans/oke-t-i-v-i-b-n-curious-breeze.md`.
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
# 5) eval + rebuild graph (thêm session recovery; nav vẫn 384):
PYTHONPATH=src python scripts/eval_goal_reaching_ac.py --checkpoint checkpoints/vjepa_ac_car/vjepa_ac_car/best.pt
PYTHONPATH=src python scripts/build_graph.py --root data/latents:data/raw:kds --root data/latents_towerpro:data/raw_towerpro:towerpro --out data/graph/topograph.pt
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
