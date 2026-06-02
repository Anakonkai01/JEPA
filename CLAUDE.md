# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Action-Conditioned World Model for RC Car Navigation based on V-JEPA 2.1**

Freeze V-JEPA 2.1 encoder (pretrained ViT-L), train only a small AC Predictor (~5M params) that learns "which action causes which visual change" in latent space. Use CEM planning to navigate toward a goal image.

Novel contribution: first evaluation of V-JEPA 2 family on a mobile robot — Meta only tested on robot arms.

Deadline: 2026-06-15.

## System Architecture

```
[RunCam WiFiLink 2]  --WFB-NG (RTL8812AU, wlan1, ch161, H.265)-->  [PC: RTX 5070 Ti]
                                                                      ffmpeg pipe
                                                                      → BGR frames 1280×720
                                                                      → V-JEPA encoder (FROZEN)
                                                                      → latent s_t (1024-dim)
                                                                      → AC Predictor
                                                                      → CEM planner
                                                                      → UDP 2 bytes
                                                                    [ESP32-S3 @ 192.168.1.23]
                                                                      → KDS N680 HV servo (steering, GPIO 5)
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
| Controller | ESP32-S3 WROOM N16R8 (16MB flash, 8MB PSRAM), IP 192.168.1.23 |
| Servo | KDS N680 HV Metal Gear Digital, 6.0–8.4V, GPIO 5, calibrated 1142–1880µs |
| ESC | Hobbywing QuicRun WP 8BL150, 150A brushless, GPIO 6, 1000–2000µs |
| Power | 20V drill battery → ESC; BEC 6V/3A → Servo; ESP32 from separate 5V |

## Daily Startup Commands

```bash
# Terminal 1: bring up WiFi adapter + start WFB-NG
bash scripts/wfb_up.sh

# Terminal 2: verify stream works
ffplay -protocol_whitelist file,rtp,udp -fflags nobuffer -flags low_delay \
       -framedrop -i ~/runcam.sdp

# Terminal 3: data collection
conda activate ai && cd src && python recorder.py

# Run existing PoC (OpenCV capture test)
python test.py
```

## V-JEPA 2.1 Notes

- **Never backprop through the encoder** — it is always frozen.
- Weights: manual download from `https://dl.fbaipublicfiles.com/vjepa2/`
- HuggingFace ID (dev/Colab only): `facebook/vjepa2-vitl-fpc64-256`
- Model variant: ViT-L, fpc64 (64 frames per clip), 256px input
- Encoder output: spatial tokens `(B, T/2, H/16, W/16, 1024)` → mean pool → `(B, 1024)`
- `torch.hub` loading fails on Colab — use HuggingFace or local checkpoint path.

## ESP32 Control Protocol

2-byte UDP packet to `192.168.1.23:4210`:
- `byte[0]`: steering (0=full left/1142µs, 127=center/1500µs, 255=full right/1880µs)
- `byte[1]`: throttle (0=full reverse/1000µs, 127=neutral/1500µs, 255=full forward/2000µs)

Mapping from float in [-1, 1]: `byte = int((value + 1.0) / 2.0 * 255)`
Servo PWM: `1142 + byte/255 * 738` µs (calibrated limits, see `firmware/specs.md`)
ESC PWM: `1000 + byte/255 * 1000` µs

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

## Firmware (firmware/)

PlatformIO project, Arduino Core 3.x via pioarduino fork. Board: `esp32-s3-devkitc-1`, N16R8.

Current state: Serial + WiFi/UDP control working. Servo calibrated, ESC arms on boot,
static IP 192.168.1.23, watchdog 500ms (neutral on timeout).

ESC arming: output neutral (1500µs) immediately on boot, wait ~2s before accepting commands.
Watchdog: return to neutral if no UDP packet received within 500ms.

### ⚠️ Outstanding firmware mismatch (2026-06-02)

- **ESC physically set to Running Mode 3 (direct reverse)** via SET-button programming
  (no program card). Hold SET while powering on → red LED ×3 = Mode 3 → power off to save.
  Verified against official QuicRun WP 8BL150 manual.
- **But `firmware/src/main.cpp` still implements the old Mode 2 double-tap reverse**
  (`tickReverse`, `REV_ARM1/2`, `doReverseSerial`, byte<64 threshold). This NO LONGER
  matches the hardware. Needs rewrite to a direct linear throttle map:
  `esc_us = 1000 + byte[1]/255 * 1000` (0=full reverse, 127≈neutral, 255=full forward) —
  which is what the "ESP32 Control Protocol" section above already describes.
- **`src/controller.py` also needs updating**: its reverse branch maps `[-1,0)` → byte `[0,63]`
  for the double-tap path. With Mode 3, use the symmetric map `byte = int((throttle+1)/2*255)`.

### WiFi reachability

Firmware hardcodes `WIFI_SSID "Hoang Kim"`. The ESP32 is only reachable from the PC when
**both are on the same WiFi/router**. If `ping 192.168.1.23` fails (ARP INCOMPLETE), check
the PC's current SSID vs the firmware SSID. The camera path (WFB-NG on `wlan1` monitor mode)
is fully independent of this — different adapter, no IP, does not use the router.

## Development Phases

See `PLAN.md` for the full roadmap (deadline 2026-06-15).

- **Phase 1** (Infrastructure): `firmware/` ESP32 WiFi+UDP, `src/capture.py`, `src/encoder.py`, `src/controller.py`
- **Phase 2** (Data): `src/recorder.py`, `src/offline_encode.py`
- **Phase 3** (Training): `src/ac_predictor.py`, `src/train.py`, `src/baselines/`
- **Phase 4** (Planning): `src/cem_planner.py`, `src/inference_loop.py`
