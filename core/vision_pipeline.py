"""Unified vision pipeline — preview rendering + face recognition off the UI thread."""

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from core.camera_service import CameraService
from core.face_engine import FaceEngine, MATCH_THRESHOLD
from core.face_quality import validate_enrollment_face
from ui.image_utils import draw_face_overlay_inplace, draw_instruction_banner_inplace


@dataclass
class OverlayState:
    bbox: Optional[tuple[int, int, int, int]] = None
    matched: bool = False
    instruction: str = ""


@dataclass
class RecognitionUpdate:
    face_count: int
    bbox: Optional[tuple[int, int, int, int]]
    match: Optional[tuple[dict, float]]
    frame: Optional[np.ndarray]


class VisionPipeline:
    """
    Background worker for:
      - preview frame rendering
      - throttled face recognition (cosine match against stored embeddings)
      - enrollment capture with quality checks
    """

    def __init__(self, camera: CameraService, face_engine: FaceEngine):
        self._camera = camera
        self._engine = face_engine
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._display_size = (480, 360)
        self._overlay = OverlayState()
        self._overlay_lock = threading.Lock()

        self._recognition_enabled = False
        self._employees: list[dict] = []
        self._recognition_interval = 1.8
        self._last_recognition = 0.0

        self._pil_queue: queue.Queue = queue.Queue(maxsize=1)
        self._result_queue: queue.Queue = queue.Queue(maxsize=1)

        self._capture_requests: queue.Queue = queue.Queue(maxsize=1)
        self._capture_results: queue.Queue = queue.Queue(maxsize=1)

    def configure_preview(self, width: int, height: int, instruction: str = "") -> None:
        self._display_size = (width, height)
        with self._overlay_lock:
            self._overlay.instruction = instruction

    def set_overlay(
        self,
        bbox: Optional[tuple[int, int, int, int]],
        matched: bool = False,
    ) -> None:
        with self._overlay_lock:
            self._overlay.bbox = bbox
            self._overlay.matched = matched

    def enable_recognition(self, employees: list[dict]) -> None:
        self._employees = employees
        self._recognition_enabled = True
        self._last_recognition = 0.0

    def disable_recognition(self) -> None:
        self._recognition_enabled = False
        self._employees = []
        with self._overlay_lock:
            self._overlay.bbox = None
            self._overlay.matched = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="Vision", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._drain(self._pil_queue)
        self._drain(self._result_queue)
        self._drain(self._capture_requests)
        self._drain(self._capture_results)

    def poll_frame(self) -> Optional[Image.Image]:
        try:
            return self._pil_queue.get_nowait()
        except queue.Empty:
            return None

    def poll_result(self) -> Optional[RecognitionUpdate]:
        try:
            return self._result_queue.get_nowait()
        except queue.Empty:
            return None

    def request_capture(self, frame: np.ndarray) -> None:
        self._drain(self._capture_requests)
        self._drain(self._capture_results)
        try:
            self._capture_requests.put_nowait(frame.copy())
        except queue.Full:
            pass

    def poll_capture(self) -> Optional[tuple[bool, str, Optional[np.ndarray], Optional[np.ndarray]]]:
        """Returns (success, message, frame, embedding)."""
        try:
            return self._capture_results.get_nowait()
        except queue.Empty:
            return None

    def _loop(self) -> None:
        preview_interval = 1.0 / 10.0
        while self._running:
            loop_start = time.monotonic()

            frame = self._camera.get_frame_copy()
            if frame is None:
                time.sleep(0.05)
                continue

            self._handle_capture_requests(frame)

            now = time.monotonic()
            if (
                self._recognition_enabled
                and self._engine.is_ready
                and self._employees
                and now - self._last_recognition >= self._recognition_interval
            ):
                self._run_recognition(frame)
                self._last_recognition = now

            pil = self._render_preview(frame)
            self._put_latest(self._pil_queue, pil)

            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, preview_interval - elapsed))

    def _handle_capture_requests(self, frame: np.ndarray) -> None:
        try:
            req = self._capture_requests.get_nowait()
        except queue.Empty:
            return

        if not self._engine.is_ready:
            self._put_latest(
                self._capture_results,
                (False, "Face engine not ready", None, None),
            )
            return

        faces = self._engine.detect_faces(req)
        if len(faces) == 0:
            self._put_latest(
                self._capture_results,
                (False, "No face detected — try again", None, None),
            )
            return
        if len(faces) > 1:
            self._put_latest(
                self._capture_results,
                (False, "Multiple faces detected — only one person", None, None),
            )
            return

        face = faces[0]
        try:
            validate_enrollment_face(req, face.bbox, face.confidence)
        except ValueError as exc:
            self._put_latest(
                self._capture_results,
                (False, str(exc), None, None),
            )
            return

        self._put_latest(
            self._capture_results,
            (True, "", req.copy(), faces[0].embedding.copy()),
        )

    def _run_recognition(self, frame: np.ndarray) -> None:
        faces = self._engine.detect_faces(frame)
        count = len(faces)
        bbox: Optional[tuple[int, int, int, int]] = None
        match: Optional[tuple[dict, float]] = None

        if count == 1:
            face = faces[0]
            bbox = face.bbox
            match = self._engine.find_best_match(
                face.embedding, self._employees, MATCH_THRESHOLD
            )
            self.set_overlay(bbox, matched=match is not None)
        else:
            self.set_overlay(None, matched=False)

        update = RecognitionUpdate(
            face_count=count,
            bbox=bbox,
            match=match,
            frame=frame.copy() if match else None,
        )
        self._put_latest(self._result_queue, update)

    def _render_preview(self, frame: np.ndarray) -> Image.Image:
        display = frame
        with self._overlay_lock:
            instruction = self._overlay.instruction
            bbox = self._overlay.bbox
            matched = self._overlay.matched

        if instruction:
            display = draw_instruction_banner_inplace(display, instruction)
        if bbox is not None:
            display = draw_face_overlay_inplace(display, bbox, matched=matched)

        w, h = self._display_size
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        small = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)
        return Image.fromarray(small)

    @staticmethod
    def _put_latest(q: queue.Queue, item) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
        try:
            q.put_nowait(item)
        except queue.Full:
            pass

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
