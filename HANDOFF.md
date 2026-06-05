# HANDOFF — đọc cái này trước khi tiếp tục

> Tóm tắt tình hình cho phiên sau. Cập nhật: **2026-06-06**.
> Nền đầy đủ: [CLAUDE.md](CLAUDE.md) · [PLAN.md](PLAN.md) · [android/README.md](android/README.md) ·
> [android/DRIVE_SETUP.md](android/DRIVE_SETUP.md). Cập nhật file này mỗi khi trạng thái đổi.

## Dự án 1 dòng
Action-Conditioned World Model cho xe RC dựa trên **V-JEPA 2.1** (encoder ViT-L đóng băng, chỉ train AC
Predictor ~5M, CEM planning). Thu data bằng **điện thoại Android đặt trên xe**. Deadline **2026-06-15**.

## Trạng thái phase
- **Phase 1 (hạ tầng):** ✅ firmware ESP32, ESP-NOW LR.
- **Phase 2 (data):** ✅ app onboard (đầy đủ) + `src/sync.py` xong. ⏳ còn `offline_encode.py` (cần weights).
- **Phase 3 (training):** ⏳ chưa (`ac_predictor.py`, `train.py`, baselines).
- **Phase 4 (planning):** ⏳ chưa (`cem_planner.py`, `inference_loop.py`; `controller.py` còn UDP cũ).

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
- **34 session** thu 2026-06-05; **29 usable** (27 công viên ngoài trời app-cũ + 2 trong nhà app-mới) =
  **55,633 frame** (~115ph @8Hz). 5 session rác/test (đứng yên/không telemetry) tự loại.
- Mỗi session usable có: `frames/*.jpg` (640×360), `telemetry.csv` (50Hz), **`actions_synced.csv`** (DÙNG cái
  này: frame_idx,t_scene_ms,steering,throttle,mode), **`imu_synced.csv`** (gx,gy,gz,ax,ay,az,rx,ry,rz),
  + IMU thô + gps + meta.json. **`actions.csv` là gốc lệch giờ — bỏ.**
- **Steering** đủ dải −1..1 (tốt); **throttle ~hằng** (giới hạn EPA) → world model hiện ≈ steering-only.
  → **việc thu tiếp: mẻ data GA BIẾN THIÊN**.
- Backup Drive: `rclone copy data/raw gdrive:JEPA/raw` (remote `gdrive:` đã cấu hình; folder nhiều file nhỏ
  nên up chậm/vài giờ, resumable). Bạn của user đang thử data này.

## Lấy / xử lý data (lệnh hay dùng)
```bash
# Build + cài app (JDK21 snap android-studio + gradle-8.13; KHÔNG có gradlew trong repo)
JAVA_HOME=/snap/android-studio/current/jbr ~/.gradle/wrapper/dists/gradle-8.13-bin/*/gradle-8.13/bin/gradle \
  -p android assembleDebug
/home/pc5070ti/Android/Sdk/platform-tools/adb install -r android/app/build/outputs/apk/debug/app-debug.apk
# Lấy data: adb pull, hoặc MTP (gvfs), hoặc rclone từ Drive
python src/sync.py            # → actions_synced.csv + imu_synced.csv mỗi session
python tools/make_video.py data/raw/session_XXXX   # video kiểm tra
rclone copy data/raw gdrive:JEPA/raw -P            # đẩy lên Drive
```

## Gotcha
- **Cài lại app**: keystore debug máy này (pc5070ti, SHA-1 `B3:FA:22:..:3C:3D`) ≠ keystore APK cũ (máy khác)
  → `INSTALL_FAILED_UPDATE_INCOMPATIBLE` → phải `adb pull` hết session **TRƯỚC** rồi `adb uninstall` + cài lại
  (gỡ app XOÁ `Android/data/.../sessions`). Đã backup đủ 34 session về `data/raw/` rồi.
- **Cắm phone vào ESP32 = cổng NATIVE (303A); nạp firmware = cổng CH343.** Đừng cấp 5V ngoài khi đang cắm phone.
- `data/` + `android/app/build/` đều gitignored.

## Bước tiếp theo gợi ý
1. **Thu mẻ data ga biến thiên** (app đã sẵn sàng, δ_cam tự khử).
2. `src/offline_encode.py`: tải **weights V-JEPA ViT-L** (`checkpoints/` rỗng; env `ai` có torch 2.10+cu128
   trên RTX 5070 Ti, transformers 5.5) → encode latent (cân nhắc crop ~35% đáy bỏ thân xe) → `data/latents/*.pt`.
3. Phase 3: `src/ac_predictor.py` + `src/train.py` (+ baseline vision-only vs vision+IMU — data đã có `imu_synced`).
