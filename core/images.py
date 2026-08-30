"""Shared image helpers for the web API."""

from __future__ import annotations

import base64

import cv2
import numpy as np


def decode_image_b64(data_b64: str) -> np.ndarray:
    raw = data_b64.split(",", 1)[-1]
    buf = base64.b64decode(raw)
    arr = np.frombuffer(buf, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Invalid image data")
    return frame
