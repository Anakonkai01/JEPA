import subprocess
import numpy as np
import cv2

W, H = 1280, 720  # phải khớp với config camera

proc = subprocess.Popen([
    "ffmpeg",
    "-protocol_whitelist", "file,rtp,udp",
    "-fflags", "nobuffer",
    "-flags", "low_delay",
    "-i", "/home/anakonkai/runcam.sdp",   # SDP file
    "-pix_fmt", "bgr24",                  # format OpenCV dùng
    "-f", "rawvideo",                     # output raw bytes
    "-"                                   # stdout
], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

frame_bytes = W * H * 3  # mỗi frame = W*H pixels * 3 màu (BGR)

stdout = proc.stdout
assert stdout is not None

while True:
    raw = stdout.read(frame_bytes)
    if len(raw) < frame_bytes:
        break  # stream kết thúc hoặc lỗi

    frame = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3))

    # frame là numpy array BGR — dùng bình thường với OpenCV
    cv2.imshow("camera", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

proc.terminate()
cv2.destroyAllWindows()