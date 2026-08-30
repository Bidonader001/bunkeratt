"""Camera overlays matching the Access Pass viewfinder language."""

import cv2
import customtkinter as ctk
import numpy as np
from PIL import Image


def draw_face_overlay_inplace(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    matched: bool = False,
) -> np.ndarray:
    out = frame if frame.flags.writeable else frame.copy()
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    corner = max(16, min(40, w // 4, h // 4))
    thickness = 3 if matched else 2
    color = (255, 255, 255)

    def bracket(ax, ay, dx, dy):
        cv2.line(out, (ax, ay), (ax + dx * corner, ay), color, thickness)
        cv2.line(out, (ax, ay), (ax, ay + dy * corner), color, thickness)

    bracket(x1, y1, 1, 1)
    bracket(x2, y1, -1, 1)
    bracket(x1, y2, 1, -1)
    bracket(x2, y2, -1, -1)

    label = "ACCESS GRANTED" if matched else "SCANNING"
    cv2.putText(
        out,
        label,
        (x1, max(y1 - 12, 22)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        color,
        1,
        cv2.LINE_AA,
    )
    return out


def draw_instruction_banner_inplace(frame: np.ndarray, text: str) -> np.ndarray:
    out = frame if frame.flags.writeable else frame.copy()
    h, w = out.shape[:2]
    bar_h = 34
    y0 = h - bar_h
    cv2.rectangle(out, (0, y0), (w, h), (0, 0, 0), -1)
    text_size = cv2.getTextSize(text.upper(), cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0]
    tx = max(8, (w - text_size[0]) // 2)
    ty = h - (bar_h - text_size[1]) // 2 - 4
    cv2.putText(
        out,
        text.upper(),
        (tx, ty),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return out


def crop_face_thumbnail(
    frame: np.ndarray, bbox: tuple[int, int, int, int], size: int = 88
) -> ctk.CTkImage:
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    pad = int(max(x2 - x1, y2 - y1) * 0.15)
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        crop = frame
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    pil_image = pil_image.resize((size, size), Image.Resampling.BILINEAR)
    return ctk.CTkImage(
        light_image=pil_image, dark_image=pil_image, size=(size, size)
    )
