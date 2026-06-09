# HANDOFF — đọc cái này trước khi tiếp tục

> Tóm tắt tình hình cho phiên sau. Cập nhật: **2026-06-09**.
> Nền đầy đủ: [../CLAUDE.md](../CLAUDE.md) · [../README.md](../README.md) · [PLAN.md](PLAN.md) ·
> [LeWorldModel.md](LeWorldModel.md) · [../robot/android/README.md](../robot/android/README.md) ·
> [../robot/android/DRIVE_SETUP.md](../robot/android/DRIVE_SETUP.md). Cập nhật file này mỗi khi trạng thái đổi.

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
- **Multi-frame clip** (feed T=4/8) = nâng cấp chính cho CONTROL (latent có motion). MẠNH hơn đổi ViT-G
  (encoder không phải bottleneck — place-rec đã sát đáy GPS). **Split latent:** giữ single-frame cho NAV
  (motion sẽ HẠI place-rec), dùng multi-frame cho CONTROL.

### Việc tiếp (ưu tiên cho phiên sau / Codex)
1. **Closed-loop N4 (cần phone A42 — user chưa mang theo):** viết `src/.../inference_loop.py` (chưa có):
   phone TCP frame → PC encode V-JEPA → `TopoGraph.localize`+`plan_route`+`extract_subgoals` → CEM
   (`CEMPlannerLatent`) lái tới subgoal → 2-byte action. Sửa `robot/capture/controller.py` (còn UDP cũ →
   serial native; throttle Mode-3 linear; **clamp cứng [-0.16, 0.15]** = giới hạn an toàn của xe).
2. **Prototype multi-frame clip cho control:** encode T=4 (sửa `engine/encode.py` unsqueeze→clip) → đo
   throttle-conditioning (eval_goal_reaching Δthrot) vs T=1. Nếu cải thiện → encode lại control latents.
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
