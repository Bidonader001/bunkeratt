"""Shared camera service — one capture thread for the whole app."""

import platform
import threading
import time
from typing import Optional

import cv2
import numpy as np

from ui import styles as s


class CameraService:
    """Low-latency webcam capture with minimal copying."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int = s.CAMERA_WIDTH,
        height: int = s.CAMERA_HEIGHT,
        fps: float = s.WEBCAM_FPS,
    ):
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._fps = fps
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_id = 0
        self._error: Optional[str] = None

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True

        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(self._camera_index, backend)
        if not self._cap.isOpened():
            self._error = "No webcam found. Please connect a camera and try again."
            if self._cap is not None:
                self._cap.release()
            self._cap = None
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._error = None
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, name="Camera", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._lock:
            self._frame = None
            self._frame_id = 0

    def _capture_loop(self) -> None:
        interval = 1.0 / self._fps
        while self._running and self._cap is not None:
            start = time.monotonic()
            ok, frame = self._cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                    self._frame_id += 1
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, interval - elapsed))

    def get_frame_copy(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def get_frame_id(self) -> int:
        with self._lock:
            return self._frame_id
