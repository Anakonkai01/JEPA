# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Action-Conditioned World Model for RC Car Navigation based on V-JEPA 2.1**

Freeze V-JEPA 2.1 encoder (pretrained ViT-L), train only a small AC Predictor (~5M params) that learns "which action causes which visual change" in latent space. Use CEM planning to navigate toward a goal image.

Novel contribution: first evaluation of V-JEPA 2 family on a mobile robot — Meta only tested on robot arms.

Deadline: 2026-06-25.

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
                                                                      → SG90 servo (steering)
                                                                      → ESC New Rain 320A (throttle)
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
| Controller | ESP32-S3 WROOM 16MB/8MB, IP 192.168.1.23 |
| Servo | SG90, PWM 1000–2000µs |
| ESC | New Rain 320A, PWM 1000–2000µs |

## Daily Startup Commands

```bash
# Terminal 1: bring up WiFi adapter in monitor mode
sudo ip link set wlan1 down && sudo iw wlan1 set monitor otherbss \
  && sudo ip link set wlan1 up && sudo iw wlan1 set channel 161 HT20

# Terminal 2: start WFB-NG receiver (decrypt + forward UDP 5600)
sudo /home/anakonkai/wfb-ng/wfb_rx -p 0 -u 5600 -K ~/gs.key -i 7669206 wlan1

# Terminal 3: verify stream works
ffplay -protocol_whitelist file,rtp,udp -fflags nobuffer -flags low_delay \
       -framedrop -i ~/runcam.sdp

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
- `byte[0]`: steering (0=full left, 127=center, 255=full right)
- `byte[1]`: throttle (0=full reverse, 127=neutral, 255=full forward)

Mapping: `byte = int((value_in_[-1,1] + 1.0) / 2.0 * 255)`
PWM range: 0→1000µs, 127→1500µs, 255→2000µs.

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
| `~/gs.key` | Ground station decryption key (64B, binary) |
| `~/drone.key` | Drone encryption key — must differ MD5 from gs.key |
| `~/wfb-ng/wfb_rx` | WFB-NG receiver binary |
| `electronic_devices/` | Full hardware setup docs (8 .md files, read README.md first) |

## Key Gotcha — WFB Keys

If decrypt fails: `~/gs.key` and the camera's `/etc/drone.key` must be a **matched keypair** (different MD5). Re-generate with `~/wfb-ng/wfb_keygen`, push new `drone.key` to camera via SCP, restart `S98wifibroadcast` on camera.

SSH to camera (needs USB-Ethernet eth0 @ 192.168.1.100):
```bash
sudo ip addr flush dev eth0 && sudo ip addr add 192.168.1.100/24 dev eth0 && sudo ip link set eth0 up
sshpass -p '12345' scp -O drone.key root@192.168.1.10:/etc/drone.key
sshpass -p '12345' ssh root@192.168.1.10 '/etc/init.d/S98wifibroadcast stop && sleep 2 && /etc/init.d/S98wifibroadcast start'
```

## Development Phases

See `PLAN.md` for the full 4-week roadmap. Phase status at project start:

- **Phase 1** (Infrastructure): `src/capture.py`, `src/encoder.py`, `src/controller.py`, `firmware/`
- **Phase 2** (Data): `src/recorder.py`, `src/offline_encode.py`
- **Phase 3** (Training): `src/ac_predictor.py`, `src/train.py`, `src/baselines/`
- **Phase 4** (Planning): `src/cem_planner.py`, `src/inference_loop.py`
