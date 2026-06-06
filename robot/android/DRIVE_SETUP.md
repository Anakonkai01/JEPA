# Setup Google Drive (upload từ app) + rclone (kéo về PC)

App upload nguyên session (.zip) lên **Drive cá nhân** của bạn (folder `JEPA`) bằng Google Sign-In
(scope `drive.file` — chỉ thấy file app tạo). PC kéo về bằng `rclone` + `tools/pull_drive.py`.

## Phần A — Google Cloud Console (để app upload được)
1. https://console.cloud.google.com → tạo project (vd `JEPA`).
2. **APIs & Services → Library** → tìm **Google Drive API** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type **External** → Create.
   - Điền App name / support email / developer email → Save.
   - **Test users** → Add → thêm **email Google của bạn** (để Testing mode là đủ, không cần publish).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Android**.
   - Package name: `com.jepa.recorder`
   - **SHA-1** (debug keystore máy này, đã lấy sẵn):
     ```
     B3:FA:22:01:30:45:E1:A5:3F:59:3F:8F:A9:84:91:E3:49:CF:3C:3D
     ```
     (Lấy lại bất cứ lúc nào:
     `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android | grep SHA1`)
   - Create. **Không cần tải file** — Android OAuth client không có secret; app xác thực bằng
     package + SHA-1.
> Build máy khác (keystore khác) hoặc build **release** → thêm SHA-1 của keystore đó vào cùng OAuth client.

Trong app: mở **📁 Sessions → Đăng nhập** → chọn tài khoản Google (đúng tài khoản đã thêm test user) →
cấp quyền Drive. Sau đó **⬆ Drive** (1 session) hoặc **⬆ Drive** trên thanh trên (tất cả session chưa gửi).

## Phần B — rclone (PC kéo về `data/raw/`)
1. Cài rclone: `sudo pacman -S rclone` (Arch) hoặc https://rclone.org/install/
2. `rclone config`:
   - `n` (new remote) → name = **gdrive** → Storage = **drive**
   - client_id / client_secret: bỏ trống (Enter)
   - scope: chọn **1** (Full access) hoặc `drive`
   - root_folder_id / service_account: bỏ trống
   - Edit advanced: `n` → Use auto config: `y` → trình duyệt mở → đăng nhập **cùng tài khoản Google** → Allow
   - Confirm → `q` thoát.
3. Test: `rclone lsd gdrive:` (sau lần upload đầu sẽ thấy folder `JEPA`).
4. Kéo về: `python tools/pull_drive.py`  (thêm `--delete-remote` nếu muốn xoá zip trên Drive sau khi giải nén).

rclone dùng full scope nên thấy được file app tạo bằng `drive.file`.
