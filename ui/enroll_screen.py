"""Register a person for Access Pass."""

import threading
from typing import Optional

import customtkinter as ctk
import numpy as np

from core import db
from core.camera_service import CameraService
from core.face_engine import FaceEngine
from core.vision_pipeline import VisionPipeline
from ui.preview_display import PreviewDisplay
from ui import styles as s


class EnrollScreen(ctk.CTkFrame):
    def __init__(
        self,
        master,
        face_engine: FaceEngine,
        camera: CameraService,
        vision: VisionPipeline,
        **kwargs,
    ):
        super().__init__(master, fg_color=s.BG_COLOR, **kwargs)
        self.face_engine = face_engine
        self.camera = camera
        self.vision = vision

        self._capture_job: Optional[str] = None
        self._captured_frames: list[np.ndarray] = []
        self._captured_embeddings: list[np.ndarray] = []
        self._saving = False
        self._capture_pending = False
        self._dots: list[ctk.CTkFrame] = []

        self._build_ui()

        self.preview = PreviewDisplay(
            self.preview_label, s.ENROLL_PREVIEW_WIDTH, s.ENROLL_PREVIEW_HEIGHT
        )

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=s.PADDING_LARGE, pady=(s.PADDING_LARGE, s.PADDING_MEDIUM))

        ctk.CTkLabel(
            header,
            text="REGISTER",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_SECONDARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Create a pass",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=28, weight="bold"),
            text_color=s.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            header,
            text="Enter identity, then capture five clear angles of the face.",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13),
            text_color=s.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(4, 0))

        form_card = ctk.CTkFrame(
            self,
            fg_color=s.CARD_COLOR,
            corner_radius=0,
            border_width=1,
            border_color=s.LINE,
        )
        form_card.pack(fill="x", padx=s.PADDING_LARGE, pady=(0, s.PADDING_MEDIUM))

        form_inner = ctk.CTkFrame(form_card, fg_color="transparent")
        form_inner.pack(fill="x", padx=s.PADDING_MEDIUM, pady=s.PADDING_MEDIUM)

        ctk.CTkLabel(
            form_inner,
            text="FULL NAME",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=10),
            text_color=s.TEXT_SECONDARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, s.PADDING_MEDIUM))

        self.name_entry = ctk.CTkEntry(
            form_inner,
            placeholder_text="Name on the pass",
            height=42,
            corner_radius=0,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
            border_width=1,
            border_color=s.LINE,
            fg_color=s.PAPER,
            text_color=s.INK,
        )
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0), padx=(0, s.PADDING_MEDIUM))

        ctk.CTkLabel(
            form_inner,
            text="PASS ID",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=10),
            text_color=s.TEXT_SECONDARY,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")

        self.id_entry = ctk.CTkEntry(
            form_inner,
            placeholder_text="Unique ID",
            height=42,
            corner_radius=0,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
            border_width=1,
            border_color=s.LINE,
            fg_color=s.PAPER,
            text_color=s.INK,
        )
        self.id_entry.grid(row=1, column=1, sticky="ew", pady=(4, 0))

        form_inner.columnconfigure(0, weight=1)
        form_inner.columnconfigure(1, weight=1)

        preview_card = ctk.CTkFrame(
            self,
            fg_color=s.INK,
            corner_radius=0,
        )
        preview_card.pack(padx=s.PADDING_LARGE, pady=(0, s.PADDING_MEDIUM))

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="STARTING CAMERA",
            width=s.ENROLL_PREVIEW_WIDTH,
            height=s.ENROLL_PREVIEW_HEIGHT,
            fg_color=s.INK,
            corner_radius=0,
            text_color=s.PAPER,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
        )
        self.preview_label.pack(padx=2, pady=2)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=s.PADDING_LARGE)

        dots_row = ctk.CTkFrame(controls, fg_color="transparent")
        dots_row.pack(side="left")
        for _ in range(s.CAPTURES_REQUIRED):
            dot = ctk.CTkFrame(
                dots_row, width=12, height=12, fg_color=s.LINE, corner_radius=6
            )
            dot.pack(side="left", padx=3)
            dot.pack_propagate(False)
            self._dots.append(dot)

        self.counter_label = ctk.CTkLabel(
            controls,
            text=f"0 / {s.CAPTURES_REQUIRED}",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
            text_color=s.TEXT_SECONDARY,
        )
        self.counter_label.pack(side="left", padx=(12, 0))

        self.warning_label = ctk.CTkLabel(
            controls,
            text="",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
            text_color=s.INK,
        )
        self.warning_label.pack(side="left", padx=(s.PADDING_MEDIUM, 0))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=s.PADDING_LARGE, pady=(s.PADDING_MEDIUM, s.PADDING_LARGE))

        self.capture_btn = ctk.CTkButton(
            btn_frame,
            text="CAPTURE",
            width=150,
            height=44,
            corner_radius=0,
            fg_color=s.INK,
            hover_color=s.INK_HOVER,
            text_color=s.PAPER,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13, weight="bold"),
            command=self._on_capture,
        )
        self.capture_btn.pack(side="left", padx=(0, s.PADDING_SMALL))

        self.save_btn = ctk.CTkButton(
            btn_frame,
            text="ISSUE PASS",
            width=160,
            height=44,
            corner_radius=0,
            fg_color=s.PAPER,
            hover_color=s.MIST,
            text_color=s.INK,
            border_width=1,
            border_color=s.INK,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13, weight="bold"),
            state="disabled",
            command=self._on_save,
        )
        self.save_btn.pack(side="left")

        self.success_frame = ctk.CTkFrame(
            self,
            fg_color=s.INK,
            corner_radius=0,
        )

    def _update_dots(self, count: int) -> None:
        for i, dot in enumerate(self._dots):
            dot.configure(fg_color=s.INK if i < count else s.LINE)

    def on_show(self) -> None:
        if not self.face_engine.is_ready:
            self.preview_label.configure(
                text=f"FACE ENGINE UNAVAILABLE\n{self.face_engine.load_error or 'Unknown error'}"
            )
            return

        if not self.camera.start():
            self.preview_label.configure(text=self.camera.error or "CAMERA ERROR")
            return

        self.vision.disable_recognition()
        self.vision.configure_preview(
            s.ENROLL_PREVIEW_WIDTH,
            s.ENROLL_PREVIEW_HEIGHT,
            "Look at the camera, then press Capture",
        )
        self.vision.start()
        self.preview.start(self.vision.poll_frame, s.PREVIEW_UI_INTERVAL_MS)

    def on_hide(self) -> None:
        self._stop_capture_poll()
        self.preview.stop()
        self.vision.stop()
        self.camera.stop()
        self._capture_pending = False

    def _on_capture(self) -> None:
        if not self.face_engine.is_ready or self._capture_pending:
            return

        frame = self.camera.get_frame_copy()
        if frame is None:
            self.warning_label.configure(text="No frame available")
            return

        self._capture_pending = True
        self.capture_btn.configure(state="disabled")
        self.warning_label.configure(text="Processing…")
        self.vision.request_capture(frame)
        self._poll_capture()

    def _poll_capture(self) -> None:
        result = self.vision.poll_capture()
        if result is None:
            self._capture_job = self.after(80, self._poll_capture)
            return

        self._capture_pending = False
        self.capture_btn.configure(state="normal")
        success, message, frame, embedding = result

        if not success:
            self.warning_label.configure(text=message)
            return

        self.warning_label.configure(text="")
        self._captured_frames.append(frame)
        self._captured_embeddings.append(embedding)
        count = len(self._captured_frames)
        self._update_dots(count)
        self.counter_label.configure(text=f"{count} / {s.CAPTURES_REQUIRED}")
        if count >= s.CAPTURES_REQUIRED:
            self.save_btn.configure(state="normal")

    def _stop_capture_poll(self) -> None:
        if self._capture_job is not None:
            self.after_cancel(self._capture_job)
            self._capture_job = None

    def _on_save(self) -> None:
        name = self.name_entry.get().strip()
        emp_id = self.id_entry.get().strip()

        if not name or not emp_id:
            self.warning_label.configure(text="Enter name and pass ID")
            return

        if db.employee_id_exists(emp_id):
            self.warning_label.configure(text="Pass ID already exists")
            return

        if len(self._captured_embeddings) < s.CAPTURES_REQUIRED:
            self.warning_label.configure(text=f"Need {s.CAPTURES_REQUIRED} captures first")
            return

        self.save_btn.configure(state="disabled")
        self.capture_btn.configure(state="disabled")
        self._saving = True

        embeddings = list(self._captured_embeddings)

        def save_task():
            try:
                avg_embedding = FaceEngine.robust_average_embeddings(embeddings)
                db.add_employee(emp_id, name, avg_embedding)
                self.after(0, self._show_success)
            except Exception as exc:
                self.after(0, lambda: self._show_save_error(str(exc)))

        threading.Thread(target=save_task, daemon=True).start()

    def _show_save_error(self, message: str) -> None:
        self._saving = False
        self.warning_label.configure(text=f"Save failed: {message}")
        self.save_btn.configure(state="normal")
        self.capture_btn.configure(state="normal")

    def _show_success(self) -> None:
        self._saving = False
        self.success_frame.pack(fill="x", padx=s.PADDING_LARGE, pady=(0, s.PADDING_LARGE))
        for widget in self.success_frame.winfo_children():
            widget.destroy()

        inner = ctk.CTkFrame(self.success_frame, fg_color="transparent")
        inner.pack(padx=s.PADDING_MEDIUM, pady=s.PADDING_MEDIUM)

        ctk.CTkLabel(
            inner,
            text="✓  PASS ISSUED",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=16, weight="bold"),
            text_color=s.PAPER,
        ).pack(side="left")

        self.after(2500, self._reset_form)

    def _reset_form(self) -> None:
        self.success_frame.pack_forget()
        self.name_entry.delete(0, "end")
        self.id_entry.delete(0, "end")
        self._captured_frames.clear()
        self._captured_embeddings.clear()
        self._update_dots(0)
        self.counter_label.configure(text=f"0 / {s.CAPTURES_REQUIRED}")
        self.warning_label.configure(text="")
        self.save_btn.configure(state="disabled")
        self.capture_btn.configure(state="normal")
