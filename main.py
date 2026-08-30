"""Access Pass — facial attendance."""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import threading

import customtkinter as ctk

from core import db
from core.camera_service import CameraService
from core.face_engine import FaceEngine
from core.vision_pipeline import VisionPipeline
from ui.attendance_screen import AttendanceScreen
from ui.branding import load_logo
from ui.enroll_screen import EnrollScreen
from ui.log_screen import LogScreen
from ui import styles as s

NAV_ITEMS = [
    ("REGISTER", "enroll"),
    ("CHECK IN", "attendance"),
    ("PASS LOG", "log"),
]


class AccessPassApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title(s.APP_NAME)
        self.geometry(f"{s.WINDOW_WIDTH}x{s.WINDOW_HEIGHT}")
        self.minsize(s.MIN_WIDTH, s.MIN_HEIGHT)
        self.configure(fg_color=s.BG_COLOR)

        self._center_window()

        db.init_db()

        self.face_engine = FaceEngine()
        self._engine_ready = False
        self.camera = CameraService()
        self.vision = VisionPipeline(self.camera, self.face_engine)

        self._current_screen_key: str | None = None
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._screens: dict[str, ctk.CTkFrame] = {}
        self._loading_label: ctk.CTkLabel | None = None

        self._build_layout()
        self._show_loading_overlay()
        self._load_engine_async()
        self._show_screen("enroll")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_window(self) -> None:
        self.update_idletasks()
        w = s.WINDOW_WIDTH
        h = s.WINDOW_HEIGHT
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _show_loading_overlay(self) -> None:
        self._loading_label = ctk.CTkLabel(
            self,
            text="LOADING RECOGNITION MODEL",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_SECONDARY,
        )
        self._loading_label.place(relx=0.5, rely=0.97, anchor="s")

    def _load_engine_async(self) -> None:
        def task():
            ready = self.face_engine.initialize()
            self.after(0, lambda: self._on_engine_loaded(ready))

        threading.Thread(target=task, daemon=True, name="ModelLoad").start()

    def _on_engine_loaded(self, ready: bool) -> None:
        self._engine_ready = ready
        if self._loading_label is not None:
            self._loading_label.destroy()
            self._loading_label = None

        if not ready:
            warn = ctk.CTkLabel(
                self,
                text="FACE MODEL FAILED TO LOAD",
                font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
                text_color=s.INK,
            )
            warn.place(relx=0.5, rely=0.97, anchor="s")

        if self._current_screen_key is not None:
            screen = self._screens[self._current_screen_key]
            if hasattr(screen, "on_hide"):
                screen.on_hide()
            if hasattr(screen, "on_show"):
                screen.on_show()

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(
            self,
            width=s.SIDEBAR_WIDTH,
            fg_color=s.SIDEBAR_COLOR,
            corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        logo_img = load_logo(188, 236, invert=True)
        if logo_img is not None:
            logo = ctk.CTkLabel(sidebar, text="", image=logo_img)
            logo.image = logo_img
            logo.pack(padx=s.PADDING_MEDIUM, pady=(22, 8))
        else:
            ctk.CTkLabel(
                sidebar,
                text=s.APP_NAME,
                font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=18, weight="bold"),
                text_color=s.SIDEBAR_TEXT,
            ).pack(padx=s.PADDING_MEDIUM, pady=(28, 4), anchor="w")
            ctk.CTkLabel(
                sidebar,
                text=s.TAGLINE,
                font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=9),
                text_color=s.SIDEBAR_MUTED,
                wraplength=180,
                justify="left",
            ).pack(padx=s.PADDING_MEDIUM, pady=(0, 20), anchor="w")

        divider = ctk.CTkFrame(sidebar, height=1, fg_color="#333333", corner_radius=0)
        divider.pack(fill="x", padx=s.PADDING_MEDIUM, pady=(4, 16))

        for label, key in NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                height=42,
                corner_radius=0,
                fg_color="transparent",
                text_color=s.SIDEBAR_MUTED,
                hover_color=s.SIDEBAR_HOVER,
                font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=13, weight="bold"),
                command=lambda k=key: self._show_screen(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[key] = btn

        foot = ctk.CTkLabel(
            sidebar,
            text=s.TAGLINE,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=9),
            text_color="#666666",
            wraplength=190,
            justify="left",
        )
        foot.pack(side="bottom", padx=s.PADDING_MEDIUM, pady=s.PADDING_LARGE, anchor="w")

        self.content = ctk.CTkFrame(self, fg_color=s.BG_COLOR, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._screens["enroll"] = EnrollScreen(
            self.content, self.face_engine, self.camera, self.vision
        )
        self._screens["attendance"] = AttendanceScreen(
            self.content, self.face_engine, self.camera, self.vision
        )
        self._screens["log"] = LogScreen(self.content)

        for screen in self._screens.values():
            screen.grid(row=0, column=0, sticky="nsew")

    def _show_screen(self, key: str) -> None:
        if self._current_screen_key == key:
            return

        if self._current_screen_key is not None:
            current = self._screens[self._current_screen_key]
            if hasattr(current, "on_hide"):
                current.on_hide()
            current.grid_remove()

        for nav_key, btn in self._nav_buttons.items():
            if nav_key == key:
                btn.configure(fg_color=s.SIDEBAR_ACTIVE, text_color=s.SIDEBAR_TEXT)
            else:
                btn.configure(fg_color="transparent", text_color=s.SIDEBAR_MUTED)

        screen = self._screens[key]
        screen.grid()
        if hasattr(screen, "on_show"):
            screen.on_show()

        if key == "log":
            screen._refresh_log()

        self._current_screen_key = key

    def _on_close(self) -> None:
        if self._current_screen_key is not None:
            current = self._screens[self._current_screen_key]
            if hasattr(current, "on_hide"):
                current.on_hide()
        self.vision.stop()
        self.camera.stop()
        self.destroy()


def main() -> None:
    app = AccessPassApp()
    app.mainloop()


if __name__ == "__main__":
    main()
