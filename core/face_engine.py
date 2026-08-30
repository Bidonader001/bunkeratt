"""InsightFace wrapper: detect faces and extract identity embeddings."""

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

MATCH_THRESHOLD = 0.55
MODEL_NAME = "buffalo_s"
DEFAULT_DET_SIZE = (320, 320)
MIN_DET_SCORE = 0.35


@dataclass
class FaceResult:
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray
    confidence: float


class FaceEngine:
    """Detect faces with InsightFace buffalo_s and match via cosine similarity."""

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        det_size: tuple[int, int] = DEFAULT_DET_SIZE,
        min_det_score: float = MIN_DET_SCORE,
    ):
        self._model_name = model_name
        self._det_size = det_size
        self._min_det_score = min_det_score
        self._app = None
        self._load_error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return self._app is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def initialize(self) -> bool:
        try:
            from insightface.app import FaceAnalysis

            self._app = FaceAnalysis(
                name=self._model_name,
                providers=["CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=-1, det_size=self._det_size)
            self._load_error = None
            return True
        except Exception as exc:
            self._load_error = str(exc)
            self._app = None
            return False

    def detect_faces(self, frame: np.ndarray) -> list[FaceResult]:
        if self._app is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        faces = self._app.get(rgb)
        results = []
        for face in faces:
            conf = float(face.det_score)
            if conf < self._min_det_score:
                continue
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox
            results.append(
                FaceResult(
                    bbox=(x1, y1, x2, y2),
                    embedding=face.embedding,
                    confidence=conf,
                )
            )
        return results

    def get_largest_face(self, frame: np.ndarray) -> Optional[FaceResult]:
        faces = self.detect_faces(frame)
        if not faces:
            return None
        return max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )

    def get_single_face(self, frame: np.ndarray) -> Optional[FaceResult]:
        faces = self.detect_faces(frame)
        if len(faces) == 1:
            return faces[0]
        return None

    @staticmethod
    def average_embeddings(embeddings: list[np.ndarray]) -> np.ndarray:
        stacked = np.stack(embeddings, axis=0)
        avg = np.mean(stacked, axis=0)
        norm = np.linalg.norm(avg)
        if norm > 0:
            avg = avg / norm
        return avg.astype(np.float32)

    @staticmethod
    def robust_average_embeddings(embeddings: list[np.ndarray]) -> np.ndarray:
        """Drop outlier captures before averaging for a tighter identity vector."""
        if len(embeddings) <= 2:
            return FaceEngine.average_embeddings(embeddings)
        avg = FaceEngine.average_embeddings(embeddings)
        scores = [FaceEngine.cosine_similarity(e, avg) for e in embeddings]
        cutoff = max(scores) - 0.12
        kept = [e for e, s in zip(embeddings, scores) if s >= cutoff]
        if len(kept) < 2:
            kept = embeddings
        return FaceEngine.average_embeddings(kept)

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a_norm = a / (np.linalg.norm(a) + 1e-8)
        b_norm = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a_norm, b_norm))

    def find_best_match(
        self,
        embedding: np.ndarray,
        employees: list[dict],
        threshold: float = MATCH_THRESHOLD,
    ) -> Optional[tuple[dict, float]]:
        best_employee = None
        best_score = threshold

        for emp in employees:
            score = self.cosine_similarity(embedding, emp["embedding"])
            if score > best_score:
                best_score = score
                best_employee = emp

        if best_employee is not None:
            return best_employee, best_score
        return None
