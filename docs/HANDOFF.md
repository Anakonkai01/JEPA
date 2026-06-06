# HANDOFF — đọc cái này trước khi tiếp tục

> Tóm tắt tình hình cho phiên sau. Cập nhật: **2026-06-07**.
> Nền đầy đủ: [../CLAUDE.md](../CLAUDE.md) · [../README.md](../README.md) · [PLAN.md](PLAN.md) ·
> [LeWorldModel.md](LeWorldModel.md) · [../robot/android/README.md](../robot/android/README.md) ·
> [../robot/android/DRIVE_SETUP.md](../robot/android/DRIVE_SETUP.md). Cập nhật file này mỗi khi trạng thái đổi.

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

## Bước tiếp theo gợi ý
1. **Thu mẻ data ga biến thiên** theo **`DATA_COLLECTION.md`** (servo mới đã calib, dual rate 14-15%, app sẵn sàng, δ_cam tự khử).
2. `src/offline_encode.py`: tải **weights V-JEPA ViT-L** (`checkpoints/` rỗng; env `ai` có torch 2.10+cu128
   trên RTX 5070 Ti, transformers 5.5) → encode latent (cân nhắc crop ~35% đáy bỏ thân xe) → `data/latents/*.pt`.
3. Phase 3: `src/ac_predictor.py` + `src/train.py` (+ baseline vision-only vs vision+IMU — data đã có `imu_synced`).
