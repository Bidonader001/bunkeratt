"""Preview display helper — minimal work on the UI thread."""

from typing import Optional

import customtkinter as ctk


class PreviewDisplay:
    """Polls pre-rendered PIL frames and updates a CTkLabel."""

    def __init__(self, label: ctk.CTkLabel, width: int, height: int):
        self._label = label
        self._width = width
        self._height = height
        self._ctk_image: Optional[ctk.CTkImage] = None
        self._job: Optional[str] = None
        self._poll_fn = None
        self._interval_ms = 100

    def start(self, poll_fn, interval_ms: int = 100) -> None:
        self._poll_fn = poll_fn
        self._interval_ms = interval_ms
        self._tick()

    def stop(self) -> None:
        if self._job is not None:
            self._label.after_cancel(self._job)
            self._job = None
        self._poll_fn = None

    def _tick(self) -> None:
        if self._poll_fn is not None:
            pil = self._poll_fn()
            if pil is not None:
                self._ctk_image = ctk.CTkImage(
                    light_image=pil,
                    dark_image=pil,
                    size=(self._width, self._height),
                )
                self._label.configure(image=self._ctk_image, text="")
        self._job = self._label.after(self._interval_ms, self._tick)
