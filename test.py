import subprocess
import numpy as np
import cv2
from datetime import datetime

W, H = 1280, 720
SDP = "/home/anakonkai/runcam.sdp"

# ffmpeg: decode RTP/H.265 stream → raw BGR frames at 30fps
proc = subprocess.Popen([
    "ffmpeg",
    "-protocol_whitelist", "file,rtp,udp",
    "-fflags", "nobuffer",
    "-flags", "low_delay",
    "-i", SDP,
    "-vf", "fps=30",
    "-pix_fmt", "bgr24",
    "-f", "rawvideo",
    "-"
], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

frame_bytes = W * H * 3
stdout = proc.stdout
assert stdout is not None

# ffmpeg recorder: nhận BGR từ stdin, encode x264 → mp4
rec_proc = None
recording = False

print("Controls: [r] record on/off  [q] quit")

while True:
    raw = stdout.read(frame_bytes)
    if len(raw) < frame_bytes:
        break

    frame = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3)).copy()

    if recording and rec_proc is not None:
        rec_proc.stdin.write(frame.tobytes())
        cv2.putText(frame, "REC", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

    cv2.imshow("camera", frame)
    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break
    elif key == ord('r'):
        if not recording:
            filename = datetime.now().strftime("rec_%Y%m%d_%H%M%S.mp4")
            rec_proc = subprocess.Popen([
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{W}x{H}", "-r", "30",
                "-i", "pipe:0",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                filename
            ], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            recording = True
            print(f"Recording → {filename}")
        else:
            recording = False
            assert rec_proc is not None
            rec_proc.stdin.close()
            rec_proc.wait()
            rec_proc = None
            print("Recording saved")

# cleanup
if rec_proc is not None:
    rec_proc.stdin.close()
    rec_proc.wait()
proc.terminate()
cv2.destroyAllWindows()
