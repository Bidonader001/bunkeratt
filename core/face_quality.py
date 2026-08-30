"""Face image quality checks for accurate enrollment."""

from __future__ import annotations

import cv2
import numpy as np


def face_area_ratio(bbox: tuple[int, int, int, int], frame_shape: tuple[int, ...]) -> float:
    x1, y1, x2, y2 = bbox
    face_area = max(0, x2 - x1) * max(0, y2 - y1)
    frame_area = max(1, frame_shape[0] * frame_shape[1])
    return face_area / frame_area


def blur_score(gray_roi: np.ndarray) -> float:
    """Laplacian variance — higher = sharper."""
    if gray_roi.size == 0:
        return 0.0
    h, w = gray_roi.shape[:2]
    if w < 160:
        scale = 160 / max(w, 1)
        gray_roi = cv2.resize(
            gray_roi,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
    return float(cv2.Laplacian(gray_roi, cv2.CV_64F).var())


def validate_enrollment_face(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    det_score: float,
    *,
    min_det_score: float = 0.18,
    min_area_ratio: float = 0.01,
    min_blur: float = 6.0,
    min_edge_margin: float = 0.0,
) -> float:
    """Validate face quality. Returns blur score on success."""
    if det_score < min_det_score:
        raise ValueError("No clear face yet — look at the camera.")

    ratio = face_area_ratio(bbox, frame.shape)
    if ratio < min_area_ratio:
        raise ValueError("Move a bit closer so we can see your face.")

    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    margin_x = w * min_edge_margin
    margin_y = h * min_edge_margin
    if min_edge_margin > 0 and (
        x1 < margin_x or y1 < margin_y or x2 > w - margin_x or y2 > h - margin_y
    ):
        raise ValueError("Center your face in the camera.")
    pad_x = int((x2 - x1) * 0.08)
    pad_y = int((y2 - y1) * 0.08)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        raise ValueError("Could not read face region.")
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    score = blur_score(gray)
    if score < min_blur:
        raise ValueError("Hold still for a moment.")
    return score
