"""Load the Access Pass logo for CustomTkinter."""

from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageOps

from ui.styles import LOGO_PATH


def _prepare(path: Path, invert: bool) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    if not invert:
        return img
    rgb = Image.merge("RGB", img.split()[:3])
    inverted = ImageOps.invert(rgb)
    return Image.merge("RGBA", (*inverted.split(), img.split()[3]))


def load_logo(width: int, height: int, *, invert: bool = False) -> ctk.CTkImage | None:
    if not LOGO_PATH.exists():
        return None
    img = _prepare(LOGO_PATH, invert=invert)
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
