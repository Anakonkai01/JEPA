"""
Thread-safe ffmpeg frame capture from WFB-NG RTP stream.
Outputs BGR frames at the configured fps and resolution.
"""

import subprocess
import threading
import queue
import numpy as np
from pathlib import Path

SDP_PATH = str(Path.home() / "runcam.sdp")
WIDTH    = 640
HEIGHT   = 360
FPS      = 10


class FrameCapture:
    def __init__(self, sdp: str = SDP_PATH, w: int = WIDTH, h: int = HEIGHT,
                 fps: int = FPS, queue_size: int = 4):
        self.sdp   = sdp
        self.w     = w
        self.h     = h
        self.fps   = fps
        self._q    = queue.Queue(maxsize=queue_size)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop  = threading.Event()

    # ------------------------------------------------------------------
    def start(self):
        self._stop.clear()
        # Không dùng fps filter — ffmpeg chạy full speed, tránh buffering H.265.
        # Decimation xuống FPS được xử lý ở recorder (lưu theo timer).
        self._proc = subprocess.Popen(
            [
                "ffmpeg",
                "-protocol_whitelist", "file,rtp,udp",
                "-fflags",  "nobuffer",
                "-flags",   "low_delay",
                "-i",       self.sdp,
                "-vf",      f"scale={self.w}:{self.h}",
                "-pix_fmt", "bgr24",
                "-f",       "rawvideo",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None

    # ------------------------------------------------------------------
    def get_frame(self, timeout: float = 1.0) -> np.ndarray | None:
        """Return latest BGR frame (H×W×3 uint8), or None on timeout."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    def _reader(self):
        frame_bytes = self.w * self.h * 3
        assert self._proc and self._proc.stdout
        stdout = self._proc.stdout

        while not self._stop.is_set():
            raw = stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.h, self.w, 3)).copy()

            # Drop oldest frame if queue is full (keep latency low)
            if self._q.full():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
            self._q.put(frame)


# ------------------------------------------------------------------
# Quick test
# ------------------------------------------------------------------
if __name__ == "__main__":
    import cv2

    cap = FrameCapture()
    cap.start()
    print(f"Capturing {WIDTH}×{HEIGHT} @ {FPS}fps — press Q to quit")

    while True:
        frame = cap.get_frame(timeout=2.0)
        if frame is None:
            print("No frame — stream down?")
            break
        cv2.imshow("capture test", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.stop()
    cv2.destroyAllWindows()
