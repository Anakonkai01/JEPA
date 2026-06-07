# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🧭 Rules for Claude — READ FIRST (added 2026-06-06)

**Session start — read in this order:**
1. **`docs/HANDOFF.md`** — the LIVE status (what's done, what's next, gotchas). Source of truth; trust
   it over older prose here when they disagree.
2. This `CLAUDE.md` (stable project facts/protocol) + `docs/PLAN.md` (roadmap).
3. App work: `robot/android/README.md`; Drive setup: `robot/android/DRIVE_SETUP.md`.

**⚠️ REPO REORGANIZED 2026-06-07 — two subsystems, paths moved.** The repo is now split into
the **ML research** package (`src/jepa_wm/`, installable via `pip install -e .`) and the
**robot rig** (`robot/`, data-collection + embedded). If older prose below references a path
that no longer exists, map it with this table (and prefer `README.md` for the live layout):

| Old path | New path |
|----------|----------|
| `src/recorder.py` `src/capture.py` `src/controller.py` | `robot/capture/…` |
| `src/sync.py` | `src/jepa_wm/data/sync.py` (run: `python scripts/sync_dataset.py`) |
| `src/encoder.py` `offline_encode.py` `ac_predictor.py` `train.py` `cem_planner.py` | `src/jepa_wm/{models,engine,planning}/…` (see `README.md`) |
| `tools/*.py` | `robot/tools/*.py` |
| `firmware/` `android/` `keys/` `setup/` | `robot/firmware/` `robot/android/` `robot/keys/` `robot/setup/` |
| `scripts/wfb_up.sh` | `robot/scripts/wfb_up.sh` |
| `docs/*` (hardware) | `robot/docs/*` |
| `PLAN.md` `HANDOFF.md` `DATA_COLLECTION.md` | `docs/*` |
| `runcam.sdp` `test.py` | `robot/runcam.sdp` `robot/test.py` |

ML entrypoints live in `scripts/` (`sync_dataset.py`, `encode_dataset.py`, `train.py`,
`evaluate.py`); configs in `configs/`. Run training scripts from the repo root after
`pip install -e .`.

**Updating context — write to the REPO, not local memory:**
- This repo is worked on from **multiple machines**. Machine-local Claude memory does NOT travel →
  **put durable status/decisions in the repo** (`HANDOFF.md` first; `CLAUDE.md`/`PLAN.md` for stable
  facts) and **commit + push**. When you finish meaningful work, update `HANDOFF.md` and commit — don't
  leave the only record in local memory.

**Avoid hallucination — verify before you claim:**
- Don't invent file paths, function names, build flags, hardware pins, or numbers. **grep/read the
  actual code/data first**; if you haven't verified something, say so explicitly.
- **Two rigs coexist in this repo.** The **NEW onboard-phone rig** (`android/`) is current for data
  collection. The **OLD WFB + PC `recorder.py` rig** (the "System Architecture" diagram, `scripts/`,
  old Hardware tables, the dated Roadmap in `PLAN.md`) is **stale for data collection — kept only as
  reference** for the protocol/firmware. Don't mix them up or quote the old rig as current.
- Recorded data lives in `data/` (**gitignored** → synced via Drive: `rclone copy data/raw
  gdrive:JEPA/raw`, remote `gdrive:`). For training use **`actions_synced.csv` + `imu_synced.csv`**
  (output of `src/sync.py`), NOT the online `actions.csv`.
- Don't restate retired assumptions as fact. Notably: the onboard rig still has a **camera capture
  latency δ_cam ≈ 100 ms** (measured on the A42) — it is NOT zero; the app records it per-frame
  (`dcam_ms`) and `src/sync.py` corrects it. (The earlier "L_cam problem fully disappears" was only
  about *clock sync*, not capture latency.)

## Project

**Action-Conditioned World Model for RC Car Navigation based on V-JEPA 2.1**

Freeze V-JEPA 2.1 encoder (pretrained ViT-L), train only a small AC Predictor (~5M params) that learns "which action causes which visual change" in latent space. Use CEM planning to navigate toward a goal image.

Novel contribution: first evaluation of V-JEPA 2 family on a mobile robot — Meta only tested on robot arms.

Deadline: 2026-06-15.

## ⚠️ ARCHITECTURE PIVOT (2026-06-04) — data collection → onboard Android phone

**The 5.8GHz WFB camera link failed at range** (≈50m: image break-up, ~3% frame stutter with
multi-second dropouts, latency ballooning 92→310ms under packet loss). Decision: **stop fighting
the wireless video link — put an Android phone ON the car** as camera + recorder + relay.

- **New data-collection rig** = `android/` app (Kotlin/CameraX, see `android/README.md`): phone's
  **ultrawide camera** captures frames locally; reads ESP32 telemetry over **USB (no-root,
  usb-serial-for-android)**; saves `frames/*.jpg + actions.csv + telemetry.csv` in the **same schema
  as `recorder.py`** → reuse `sync.py`/`offline_encode.py` unchanged. Frame & telemetry share one
  phone clock → the **WFB-latency / LED / clock-sync problems disappear**. (A residual **camera capture
  latency δ_cam ≈ 100 ms** remains — sensor→callback — now measured per-frame as `dcam_ms` and corrected
  in `src/sync.py`; see Rules above.)
- Phone (Samsung A42 5G, Android 13) ↔ **dongle** via USB (same hex protocol as `recorder.py`);
  dongle ↔ car via ESP-NOW <0.3m (now LR). **No firmware change needed.** (Later option: phone↔car
  ESP32 direct USB, drop the dongle.)
- **Inference (Phase 4) still needs the PC** (V-JEPA ViT-L runs on the RTX, not the phone): phone
  will TCP-stream frames to PC, PC computes, returns 2-byte action → phone → ESP32. Slow is OK.
- **The OpenIPC + WFB + PC-`recorder.py` path below is the PRIOR rig** — kept as fallback/reference
  and still valid for understanding the protocol/firmware.
- **Status (2026-06-05): app BUILT + tested on A42, working.** Phone plugs **directly into the car
  ESP32** over USB (dongle dropped — `main.cpp` now emits telemetry hex + reads control hex on USB,
  ESP-NOW kept as fallback). Features: **auto-REC by CH10**, fast-shutter anti-blur,
  **accel/gyro/rotvec/GPS** logging, live stream + **full-session auto-upload to PC over Tailscale**
  (no cable; `tools/pc_receiver.py` / `pc_stream_view.py`). **Cross-stream sync verified** (one phone
  clock). See memories `onboard-phone-pivot`, `android-usb-link`, `onboard-recorder-state`.
- **Status (2026-06-06): big app pass + data pipeline done.** App adds: **δ_cam fix** (frame `t_ms` =
  sensor exposure time + `dcam_ms` column; **δ_cam measured ≈ 100 ms**, `TIMESTAMP_SOURCE=REALTIME`),
  **session manager** (`SessionListActivity`/`SessionPlayerActivity`/`SessionStore`/`SessionAdapter`:
  list, playback w/ steer-throttle overlay, delete/label/info), **Google Drive upload** (`DriveUploader`,
  GoogleSignIn `drive.file` + OkHttp resumable — setup in `android/DRIVE_SETUP.md`), **dim-to-black**
  (AMOLED battery save). **`src/sync.py` done** → re-pairs frames from `telemetry.csv` at scene time
  (old data −100 ms, new data offset 0) → writes **`actions_synced.csv` + `imu_synced.csv`** per session;
  **29 usable sessions / 55,633 frames**. Tools: `tools/make_video.py` (overlay MP4), `tools/pull_drive.py`
  (rclone). Build = JDK21 (`/snap/android-studio/current/jbr`) + gradle-8.13; install via
  `~/Android/Sdk/platform-tools/adb`. **Full live status: `HANDOFF.md`.**
- **⚠️ USB PORT (2026-06-05, fixed): plug the phone into the ESP32-S3 NATIVE port** ("USB JTAG/serial
  debug unit", VID `0x303A`) — **NOT** the CH343 "USB Single Serial" port. The CH343 USB-C port lacks
  proper CC resistors, so a phone (strict USB-C host) won't power it over a direct C-to-C cable (board
  LED stays off); the native port has correct CC → phone bus-powers + enumerates it directly, **no hub
  needed**. Firmware now routes `Serial` (telemetry+control) to the native USB via build flags
  `ARDUINO_USB_MODE=1` + `ARDUINO_USB_CDC_ON_BOOT=1` (`firmware/platformio.ini` `[env:car]`). **Flash
  still via the CH343 port** (UART0 download); **run/connect-to-phone via the native port.**
  **Power on the car:** bus-power the ESP32 from the phone (native port) + common GND with the BEC —
  do NOT feed external 5V into the ESP32 while it's cabled to the phone (back-feeds the phone's VBUS →
  Samsung locks the port). See memory `usb-native-port-cc`.

## System Architecture (PRIOR rig — being replaced for data collection; see pivot above)

```
[RunCam WiFiLink 2]  --WFB-NG (RTL8812AU, wlan1, ch161, H.265)-->  [PC: RTX 5070 Ti]
                                                                      ffmpeg pipe
                                                                      → BGR frames 1280×720
                                                                      → V-JEPA encoder (FROZEN)
                                                                      → latent s_t (1024-dim)
                                                                      → AC Predictor
                                                                      → CEM planner
                                                                      → 2-byte action
                                                                      → ESP-NOW dongle (PC USB)  ⇅ ch1 unicast
                                                                    [ESP32-S3 car]
                                                                      → TowerPro MG946R servo (steering, GPIO 5)
                                                                      → Hobbywing QuicRun 8BL150 ESC (throttle, GPIO 6)
```

## Training Pipeline

```
frame_t     → V-JEPA encoder (frozen) → s_t     ─┐
action_t    ────────────────────────────────────→  AC Predictor → ŝ_{t+1}
frame_{t+1} → V-JEPA encoder (frozen) → s_{t+1}  (ground truth)

Loss: MSE(ŝ_{t+1}, s_{t+1})
```

Critical optimization: pre-encode the entire dataset through V-JEPA offline (once), save latent tensors to `data/latents/*.pt`. Training loads latents directly — no V-JEPA forward pass during training (~50-100x speedup).

## Hardware

| Component | Details |
|-----------|---------|
| Camera | RunCam WiFiLink 2, OpenIPC, IMX415, 1280×720@120fps, H.265 8Mbps CBR, GOP=1 |
| RX radio | RTL8812AU USB adapter as `wlan1`, driver: `88XXau_wfb` (DKMS) |
| WFB link | ch161 (5805MHz) HT20, link_id=7669206, radio_port=0, key=`~/gs.key` |
| Compute | Arch Linux, kernel 7.0.3, RTX 5070 Ti |
| Controller (car) | ESP32-S3 WROOM N16R8 (16MB flash, 8MB PSRAM), MAC `E0:72:A1:D5:27:B0` |
| Telemetry dongle | ESP32-S3 WROOM N16R8 on PC USB (`/dev/ttyACM*`), MAC `E0:72:A1:DB:D7:74` — ESP-NOW↔serial bridge |
| Servo | TowerPro MG946R Metal Gear (analog), 4.8–6.0V (⚠️ KHÔNG HV, tối đa ~6.6V), GPIO 5. **Recalib 2026-06-07: full range `SERVO_MIN/CENTER/MAX = 1000/1560/2000µs`** (driveNorm pivot quanh CENTER → góc lái cơ khí đối xứng, neutral=steer=0=1560). ⚠️ action→góc KHÔNG khớp data cũ KDS (C1500, dải 1150–1850) → 2 domain khác cho phần AC, xem `firmware/specs.md`. Cũ: KDS N680 HV (đã thay vì yếu/lỗi). |
| ESC | Hobbywing QuicRun 8BL150 (bản thường, không WP), 150A brushless, GPIO 6, 1000–2000µs |
| Power | 20V drill battery → ESC; BEC 6V/3A → Servo (⚠️ giữ ≤6V — MG946R không HV); ESP32 from separate 5V |

## Daily Startup Commands

```bash
# Terminal 1: bring up WiFi adapter + start WFB-NG
bash robot/scripts/wfb_up.sh

# Terminal 2: verify stream works
ffplay -protocol_whitelist file,rtp,udp -fflags nobuffer -flags low_delay \
       -framedrop -i ~/runcam.sdp

# Terminal 3: data collection (plug the ESP-NOW dongle into PC USB first)
conda activate ai && python robot/capture/recorder.py auto   # 'auto' = autodetect dongle on /dev/ttyACM*

# Run existing PoC (OpenCV capture test)
python robot/test.py
```

## V-JEPA 2.1 Notes

- **Never backprop through the encoder** — it is always frozen.
- Weights: manual download from `https://dl.fbaipublicfiles.com/vjepa2/`
- HuggingFace ID (dev/Colab only): `facebook/vjepa2-vitl-fpc64-256`
- Model variant: ViT-L, fpc64 (64 frames per clip), 256px input
- Encoder output: spatial tokens `(B, T/2, H/16, W/16, 1024)` → mean pool → `(B, 1024)`
- `torch.hub` loading fails on Colab — use HuggingFace or local checkpoint path.

## ESP32 Control Protocol (ESP-NOW via dongle)

PC ↔ car talk over **ESP-NOW** (2.4GHz peer-to-peer, no router), bridged by a USB **dongle**
ESP32-S3. PC ↔ dongle is USB serial; each line is **hex + `\n`** (self-resyncing, no COBS).
The dongle decodes a line → `esp_now_send` to the car, and forwards car telemetry back as hex.

PC → car payloads (raw bytes, hex-encoded on the serial wire):
- 2 bytes `[steer, throt]` = AUTO control:
  - `byte[0]` steering (0=full left/1150µs, 127=center/1500µs, 255=full right/1850µs)
  - `byte[1]` throttle (0=full reverse/1000µs, 127=neutral/1500µs, 255=full forward/2000µs)
- 1 byte `0x01`/`0x00` = latency LED on/off.

Mapping from float in [-1, 1]: `byte = int((value + 1.0) / 2.0 * 255)`
Servo PWM (recalib 2026-06-07, **pivot quanh tâm 1560**): `steer∈[-1,0] → 1560 + steer*560` (=[1000,1560]); `steer∈[0,1] → 1560 + steer*440` (=[1560,2000]). Full range 1000–2000, servo MG946R, see `firmware/specs.md`.
ESC PWM: `1000 + byte/255 * 1000` µs

Telemetry car → PC: 25-byte packed struct `<BBIIffHHHB>` @50Hz (magic `0xAC`, mode, seq,
esp_ms, steering/throttle floats, 3× ch µs, rec flag) — see `Telemetry` in
`firmware/src/main.cpp` and `TELEM_FMT` in `src/recorder.py`.

## Video Capture Pattern

`cv2.VideoCapture` cannot handle RTP/H.265 with SDP. Always use ffmpeg subprocess pipe:

```python
proc = subprocess.Popen([
    "ffmpeg", "-protocol_whitelist", "file,rtp,udp",
    "-fflags", "nobuffer", "-flags", "low_delay",
    "-i", "/home/anakonkai/runcam.sdp",
    "-pix_fmt", "bgr24", "-f", "rawvideo", "-"
], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
# read W*H*3 bytes per frame
```

See `test.py` for the minimal working example.

## Python Environment

- Use `/usr/bin/python3` for any build or native extension — not conda python.
- Conda env is fine for pure Python / PyTorch work.
- Shell uses zoxide (`z` alias replaces `cd`) — use absolute paths in scripts.

## Key External Files

| Path | Purpose |
|------|---------|
| `~/runcam.sdp` | RTP stream descriptor for ffplay/ffmpeg |
| `~/gs.key` | Ground station decryption key — runtime copy used by wfb_up.sh |
| `keys/gs.key` | Same key, version-controlled backup in repo |
| `keys/drone.key` | Drone encryption key — upload to camera when regenerating keypair |
| `~/wfb-ng/wfb_rx` | WFB-NG receiver binary |
| `docs/` | Full hardware setup docs (8 .md files, read README.md first) |

## Key Gotcha — WFB Keys

If decrypt fails: `~/gs.key` and the camera's `/etc/drone.key` must be a **matched keypair** (different MD5). Re-generate with `~/wfb-ng/wfb_keygen`, push new `drone.key` to camera via SCP, restart `S98wifibroadcast` on camera.

SSH to camera (needs USB-Ethernet eth0 @ 192.168.1.100):
```bash
sudo ip addr flush dev eth0 && sudo ip addr add 192.168.1.100/24 dev eth0 && sudo ip link set eth0 up
sshpass -p '12345' scp -O drone.key root@192.168.1.10:/etc/drone.key
sshpass -p '12345' ssh root@192.168.1.10 '/etc/init.d/S98wifibroadcast stop && sleep 2 && /etc/init.d/S98wifibroadcast start'
```

## Camera (OpenIPC majestic + WFB) — config & OSD

Camera is RunCam WiFiLink V3.1 (OpenIPC, `majestic` streamer). Edit settings via SSH (needs
eth0 link above), apply with `killall -1 majestic`. Read/write keys with `cli -g/-s .a.b.c`.

**Live config = `/etc/majestic.yaml`.** Current project settings (changed from FPV defaults):
`video0.size 640x360`, `video0.fps 30`, `video0.bitrate 4000`, `video0.codec h265`,
`rcMode cbr`, `gopSize 1`, `isp.exposure 5`. Rationale: pipeline downscales to 640×360 and
V-JEPA only needs 256px, so encoding 360p direct + half the bitrate cuts link load/latency
with no quality loss for the frozen encoder. Don't raise `isp.exposure` (motion blur on a
moving car) or `contrast`/`saturation` (clips info; V-JEPA normalizes its input anyway).

**Persistence gotcha.** `/usr/bin/wifibroadcast`'s `video_settings()` HARDCODES the FPV
defaults (`1280x720`, `120fps`, `8192`, `exposure 5`) and would clobber majestic.yaml — BUT
it's gated by `/etc/system.ok`, which **exists**, so it only runs on first boot or
`wifibroadcast reset`. So our majestic.yaml edits persist across normal reboots. If video
ever reverts to 720p/120/8192, it's because `system.ok` was deleted or `reset` was run.

**OSD "Waiting for data on /dev/ttyS2" (red text) = `msposd`**, NOT majestic's `osd:` (that's
already `enabled: false`) and NOT the `fpv:` plugin (that's low-latency FPV mode, keep it
`true`). `msposd` is an MSP/MAVLink OSD daemon launched unconditionally by `start_telemetry`
in `/usr/bin/wifibroadcast`; with no flight controller on `ttyS2` it just renders the waiting
banner — which would burn into the H.265 stream and pollute training frames. **Disabled by
commenting the `start_telemetry` call** (line ~160; backup at `/usr/bin/wifibroadcast.jepa-bak`).
We don't use the WFB telemetry tunnel — our telemetry is the ESP32 ESP-NOW path. To re-enable:
restore the backup. After editing, kill the running daemon immediately: `kill $(pgrep msposd)`.

## Firmware (firmware/)

PlatformIO project, Arduino Core 3.x via pioarduino fork. Board: `esp32-s3-devkitc-1`, N16R8.
**Two firmwares, two envs** (split by `build_src_filter` in `platformio.ini`):
`env:car` → `src/main.cpp` (i-BUS hub on the car); `env:dongle` → `src/dongle.cpp` (USB
ESP-NOW↔serial bridge on the PC). Build/flash with the venv pio (see Python Environment):

```bash
~/.pio-venv/bin/pio run -d robot/firmware -e car    -t upload --upload-port /dev/ttyACM1
~/.pio-venv/bin/pio run -d robot/firmware -e dongle -t upload --upload-port /dev/ttyACM0
```

**ESP-NOW link:** unicast, channel 1, **LR on** (`esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_LR)`
in both `setupEspNow()` — sensitivity to ~−94dBm for range; must match on car+dongle or no link).
Peer MACs hardcoded in `firmware/include/peers.h`.
Re-pair new boards: read MAC with `~/.pio-venv/bin/esptool --port /dev/ttyACMx read-mac`
(= the STA MAC the firmware uses), edit `peers.h`, reflash both. Boards also print their own
MAC on boot (`[ESP-NOW] MAC con nay: …`). 2.4GHz ESP-NOW does not interfere with the 5.8GHz
camera (WFB-NG) — different band, different adapter.

Current state (2026-06-03): **FlySky i-BUS hub firmware** (`firmware/src/main.cpp`).
Reads FS-iA10B i-BUS on `Serial1`/GPIO18 (115200, non-inverted). 3 modes via CH9
(`<1300` RECORD / `1300–1700` NEUTRAL / `>1700` AUTO). CH10 = record on/off flag.
Telemetry to dongle @50Hz (packed struct: steering/throttle floats + ch µs + rec flag).
ESC arms on boot (neutral ~3s). Two watchdogs: i-BUS loss >100ms → neutral; AUTO control
loss >500ms → neutral. External LED on GPIO21 (+ onboard RGB) toggled by ESP-NOW 0x01/0x00
for latency calibration. Servo range **1000–2000µs**, tâm 1560 (recalib 2026-06-07, pivot quanh tâm).

Channel map (FS-i6 modded 10ch): CH1=steering, CH2=throttle, CH9=mode, CH10=record.

### ✅ ESC Mode 3 — RESOLVED (was the 2026-06-02 mismatch)

ESC is physically in Running Mode 3 (direct reverse, set via SET-button: hold SET on
power-on → red LED ×3). Firmware now uses a **direct linear throttle map**
`esc_us = 1000 + (throttle+1)/2 * 1000` (full reverse↔neutral↔full forward); all the old
Mode-2 double-tap code (`tickReverse`, `REV_ARM1/2`) is gone. Verified on bench.

**Still pending — `src/controller.py` (AUTO/inference path, Phase 4):** two things to fix
when Phase 4 starts. (1) Transport: it still targets the old UDP socket — switch to the
**dongle serial** (write 2-byte control as hex + `\n`, same as `recorder.py`'s `send`).
(2) Throttle map: its reverse branch still maps `[-1,0)` → byte `[0,63]` (old Mode-2
double-tap); for Mode 3 use the symmetric `byte = int((throttle+1)/2*255)`. Not used during
data collection, so deferred.

### Data collection (FlySky, not WASD)

Car is driven manually by FlySky during RECORD; `src/recorder.py` is a **passive logger**:
receives telemetry → ring buffer → pairs each frame with the action at `t_read − latency`,
where `latency` is measured **in realtime** by flashing the GPIO21 LED inside a fixed
masked corner of the frame (`tools/set_led_roi.py` sets the bbox; tracker re-measures every
~2s). `data/camera_latency.txt` is a fallback (currently `0.092`, the trustworthy in-shade
median). The masked LED bbox is blacked out before saving so V-JEPA never sees the blinking
light. Action recorded = normalized stick [−1,1] (remote D/R/EPA shapes it before i-BUS →
recorded = actual command, fully synced).

**Latency strategy = fixed-from-shade (authoritative).** L_cam is **light-independent** (camera
exposure/encode are locked), so the realtime LED tracker is NOT needed outdoors — it fails in
direct midday sun (sun floods the ROI → bogus sub-40ms latencies; real floor ~88ms). Measure
L_cam **once in shade** with `tools/measure_latency.py` (LED-flash, median of 15; LED is
electrically instantaneous → measures **pure** camera latency) → it writes `camera_latency.txt`,
which the recorder uses as the fixed fallback. **No shrouding needed** — just don't measure in
sun. The LED stays only as an in-shade *verifier* (and re-measure after changing camera
settings). The tracker now self-protects: rejects out-of-range latencies (`LAT_MIN`/`LAT_MAX`),
requires a synchronous relative rise (`RISE_MIN` above the pre-flash baseline), and shows
`LED:SUN` (red) + falls back to `camera_latency.txt` when saturated. See memory `led-latency-sun`.

Note: a **motion cross-correlation** (optical-flow ↔ steering) cannot replace the LED for
alignment — its lag is `L_cam + τ_vehicle` (steering→visible-yaw delay, 50–150ms), whereas data
alignment needs *pure* L_cam (vehicle dynamics is what the predictor must learn, not absorb into
the offset). Motion-corr is only a coarse sanity check.

**Sync robustness (per-session outputs).** Each session now writes `telemetry.csv` — the full
**raw 50Hz telemetry stream** (`t_recv`, `seq`, `esp_ms`, steer, throt, mode) — so alignment
can be **re-done offline with any L_cam** (don't bake a possibly-wrong latency into the data).
`actions.csv` remains the online best-effort pairing. When telemetry drops (weak/far signal),
the frame's nearest action sample lands >`MATCH_TOL` (50ms) from `t_scene` → the frame is
**dropped** (not paired with a stale action); the HUD shows `skip:N` and the end-of-session
line reports it. A deferred offline `src/sync.py` (Phase-2/3, built with `offline_encode.py`)
will re-pair each frame at `t_read − L_cam` (recovered as `t_scene + latency`) by **linearly
interpolating** steer/throt from `telemetry.csv` at the fixed L_cam, dropping telemetry-gap
frames, and writing `actions_synced.csv` (originals untouched).

### ESP-NOW link (replaces old WiFi/UDP telemetry)

Telemetry/control no longer use the home router — the car ESP32 and the USB dongle talk
**ESP-NOW** directly (2.4GHz, channel 1, unicast), so it works anywhere with no SSID/IP.
If the recorder shows `NO TELEM`: confirm the dongle is plugged in (`ls /dev/ttyACM*`), the
right port is picked (`python recorder.py auto` autodetects the one emitting valid `0xAC`
frames), the car is powered, and both boards share channel 1 with matching MACs in `peers.h`.
The camera path (WFB-NG on `wlan1` monitor mode, 5.8GHz) is fully independent.

> The old eth0/wlan0 `192.168.1.0/24` subnet conflict that broke ESP32-over-WiFi no longer
> applies to telemetry (ESP-NOW has no IP). It still matters **only for SSHing the camera**
> (eth0 @ 192.168.1.100/24, see "SSH to camera"): when eth0 is up its route can shadow wlan0.
> Flush eth0 when done configuring the camera — `sudo ip addr flush dev eth0`.

**Gotcha — `data/` is gitignored**, so a fresh clone has no `data/led_roi.json`. Without it
the recorder disables the LatencyTracker → LED never blinks and frames aren't masked. Run
`python robot/tools/set_led_roi.py` once per machine to recreate it (bbox is in 640×360 space).

## Development Phases

See `docs/PLAN.md` for the full roadmap (deadline 2026-06-15).

- **Phase 1** (Infrastructure): `robot/firmware/` ESP32 ESP-NOW (car + dongle), `robot/capture/capture.py`, `src/jepa_wm/models/encoders/vjepa.py`, `robot/capture/controller.py`
- **Phase 2** (Data): `robot/capture/recorder.py`, `src/jepa_wm/data/sync.py`, `src/jepa_wm/engine/encode.py`
- **Phase 3** (Training): `src/jepa_wm/models/{ac_predictor,leworldmodel}.py`, `src/jepa_wm/engine/train.py`, `src/jepa_wm/models/baselines/`
- **Phase 4** (Planning): `src/jepa_wm/planning/cem.py`, `scripts/evaluate.py` (online loop)
