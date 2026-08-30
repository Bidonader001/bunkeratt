"""Live check-in for Access Pass."""

from datetime import datetime
from typing import Optional

import customtkinter as ctk

from core import db
from core.camera_service import CameraService
from core.face_engine import FaceEngine
from core.vision_pipeline import VisionPipeline
from ui.image_utils import crop_face_thumbnail
from ui.preview_display import PreviewDisplay
from ui import styles as s

INSTRUCTION = "Look at the camera and hold still"


class AttendanceScreen(ctk.CTkFrame):
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

        self._result_job: Optional[str] = None
        self._last_match_employee_id: Optional[str] = None
        self._employees: list[dict] = []
        self._ui_state = "neutral"
        self._neutral_text = ""

        self._build_ui()

        self.preview = PreviewDisplay(
            self.preview_label, s.PREVIEW_WIDTH, s.PREVIEW_HEIGHT
        )

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=s.PADDING_LARGE, pady=(s.PADDING_LARGE, s.PADDING_MEDIUM))

        ctk.CTkLabel(
            header,
            text="CHECK IN",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_SECONDARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Scan for access",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=28, weight="bold"),
            text_color=s.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 0))

        self.instructions = ctk.CTkLabel(
            header,
            text=INSTRUCTION,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13),
            text_color=s.TEXT_SECONDARY,
            anchor="w",
        )
        self.instructions.pack(anchor="w", pady=(4, 0))

        status_row = ctk.CTkFrame(self, fg_color="transparent")
        status_row.pack(anchor="w", padx=s.PADDING_LARGE, pady=(0, s.PADDING_SMALL))

        self.status_dot = ctk.CTkLabel(
            status_row, text="●", font=ctk.CTkFont(size=10), text_color=s.TEXT_NEUTRAL
        )
        self.status_dot.pack(side="left")

        self.status_label = ctk.CTkLabel(
            status_row,
            text="SCANNING",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_NEUTRAL,
        )
        self.status_label.pack(side="left", padx=(6, 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=s.PADDING_LARGE, pady=(0, s.PADDING_LARGE))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        preview_card = ctk.CTkFrame(content, fg_color=s.INK, corner_radius=0)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, s.PADDING_MEDIUM))

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="STARTING CAMERA",
            width=s.PREVIEW_WIDTH,
            height=s.PREVIEW_HEIGHT,
            fg_color=s.INK,
            corner_radius=0,
            text_color=s.PAPER,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
        )
        self.preview_label.pack(padx=2, pady=2, expand=True)

        result_card = ctk.CTkFrame(
            content,
            fg_color=s.PAPER,
            corner_radius=0,
            border_width=1,
            border_color=s.LINE,
        )
        result_card.grid(row=0, column=1, sticky="nsew")

        self.result_inner = ctk.CTkFrame(result_card, fg_color="transparent")
        self.result_inner.pack(
            expand=True, fill="both", padx=s.PADDING_MEDIUM, pady=s.PADDING_MEDIUM
        )

        self._build_result_widgets()

        self.empty_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13),
            text_color=s.TEXT_SECONDARY,
        )

    def _build_result_widgets(self) -> None:
        self.neutral_frame = ctk.CTkFrame(self.result_inner, fg_color="transparent")
        self.neutral_frame.pack(expand=True, fill="both")

        ctk.CTkLabel(
            self.neutral_frame,
            text="[  ]",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=28),
            text_color=s.INK,
        ).pack(pady=(s.PADDING_LARGE, s.PADDING_SMALL))

        self.neutral_msg = ctk.CTkLabel(
            self.neutral_frame,
            text="Align your face\nin the viewfinder",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=15),
            text_color=s.TEXT_PRIMARY,
            wraplength=220,
            justify="center",
        )
        self.neutral_msg.pack(pady=(0, s.PADDING_SMALL))

        ctk.CTkLabel(
            self.neutral_frame,
            text="Match is automatic",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
            text_color=s.TEXT_SECONDARY,
            wraplength=220,
        ).pack(pady=(0, s.PADDING_LARGE))

        self.success_frame = ctk.CTkFrame(self.result_inner, fg_color="transparent")

        self.success_check = ctk.CTkLabel(
            self.success_frame,
            text="✓  ACCESS GRANTED",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14, weight="bold"),
            text_color=s.INK,
        )
        self.success_check.pack(pady=(s.PADDING_MEDIUM, s.PADDING_SMALL))

        self.success_thumb = ctk.CTkLabel(self.success_frame, text="")
        self.success_thumb.pack(pady=s.PADDING_SMALL)

        self.success_name = ctk.CTkLabel(
            self.success_frame,
            text="",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=20, weight="bold"),
            text_color=s.TEXT_PRIMARY,
        )
        self.success_name.pack(pady=(s.PADDING_SMALL, 4))

        self.success_time = ctk.CTkLabel(
            self.success_frame,
            text="",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
            text_color=s.TEXT_SECONDARY,
        )
        self.success_time.pack()

        self.success_conf = ctk.CTkLabel(
            self.success_frame,
            text="",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_NEUTRAL,
        )
        self.success_conf.pack(pady=(s.PADDING_SMALL, s.PADDING_MEDIUM))

    def _set_neutral(self, message: str) -> None:
        if self._ui_state != "neutral":
            self.success_frame.pack_forget()
            self.neutral_frame.pack(expand=True, fill="both")
            self._ui_state = "neutral"
        if self._neutral_text != message:
            self.neutral_msg.configure(text=message)
            self._neutral_text = message

    def _set_success(
        self, name: str, thumbnail: ctk.CTkImage, confidence: float, timestamp: str
    ) -> None:
        if self._ui_state != "success":
            self.neutral_frame.pack_forget()
            self.success_frame.pack(expand=True, fill="both")
            self._ui_state = "success"
        self.success_thumb.configure(image=thumbnail)
        self.success_thumb.image = thumbnail
        self.success_name.configure(text=name)
        self.success_time.configure(text=timestamp)
        self.success_conf.configure(text=f"MATCH  {confidence:.0%}")

    def _show_empty_employees(self) -> None:
        self.empty_label.configure(
            text="No passes issued yet. Open REGISTER to enroll a face first."
        )
        self.empty_label.pack(pady=(0, s.PADDING_MEDIUM))
        self.instructions.configure(text="Issue at least one pass before check-in.")
        self.status_label.configure(text="WAITING")
        self.status_dot.configure(text_color=s.INK)

    def _hide_empty_employees(self) -> None:
        self.empty_label.pack_forget()
        self.instructions.configure(text=INSTRUCTION)

    def on_show(self) -> None:
        self._employees = db.get_all_employees()
        self._last_match_employee_id = None
        self._ui_state = ""
        self._neutral_text = ""

        if not self.face_engine.is_ready:
            self.preview_label.configure(
                text=f"FACE ENGINE UNAVAILABLE\n{self.face_engine.load_error or 'Unknown error'}"
            )
            return

        if not self._employees:
            self._show_empty_employees()
            self.vision.disable_recognition()
        else:
            self._hide_empty_employees()
            self.vision.enable_recognition(self._employees)

        if not self.camera.start():
            self.preview_label.configure(text=self.camera.error or "CAMERA ERROR")
            return

        self.vision.configure_preview(s.PREVIEW_WIDTH, s.PREVIEW_HEIGHT, INSTRUCTION)
        self.vision.start()
        self.preview.start(self.vision.poll_frame, s.PREVIEW_UI_INTERVAL_MS)

        self._set_neutral("Align your face\nin the viewfinder")
        self._start_result_poll()

    def on_hide(self) -> None:
        self._stop_result_poll()
        self.preview.stop()
        self.vision.disable_recognition()
        self.vision.stop()
        self.camera.stop()
        self._last_match_employee_id = None

    def _start_result_poll(self) -> None:
        self._poll_results()

    def _stop_result_poll(self) -> None:
        if self._result_job is not None:
            self.after_cancel(self._result_job)
            self._result_job = None

    def _poll_results(self) -> None:
        update = self.vision.poll_result()
        if update is not None:
            self._handle_result(update)
        self._result_job = self.after(200, self._poll_results)

    def _handle_result(self, update) -> None:
        if update.face_count == 0:
            self.status_dot.configure(text_color=s.TEXT_NEUTRAL)
            self.status_label.configure(text="SCANNING")
            if self._ui_state != "success":
                self._set_neutral("Align your face\nin the viewfinder")
            return

        if update.face_count > 1:
            self.status_dot.configure(text_color=s.INK)
            self.status_label.configure(text="MULTIPLE FACES")
            self._set_neutral("One person at a time")
            return

        if update.match is None:
            self.status_dot.configure(text_color=s.TEXT_NEUTRAL)
            self.status_label.configure(text="NO MATCH")
            if self._ui_state != "success":
                self._set_neutral("No match — try again")
            return

        employee, confidence = update.match
        self.status_dot.configure(text_color=s.INK)
        self.status_label.configure(text="ACCESS GRANTED")

        now = datetime.now()
        timestamp = now.strftime("%I:%M %p · %b %d, %Y")

        if update.frame is not None and update.bbox is not None:
            thumbnail = crop_face_thumbnail(update.frame, update.bbox)
            self._set_success(employee["name"], thumbnail, confidence, timestamp)

        emp_id = employee["employee_id"]
        if emp_id != self._last_match_employee_id:
            if not db.has_recent_checkin(emp_id, s.DUPLICATE_CHECKIN_MINUTES):
                db.log_attendance(emp_id, employee["name"], confidence)
            self._last_match_employee_id = emp_id
