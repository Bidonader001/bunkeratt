"""Pass log viewer."""

from datetime import datetime

import customtkinter as ctk

from core import db
from ui import styles as s


class LogScreen(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=s.BG_COLOR, **kwargs)
        self._build_ui()

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=s.PADDING_LARGE, pady=(s.PADDING_LARGE, s.PADDING_MEDIUM))

        ctk.CTkLabel(
            header,
            text="PASS LOG",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=11),
            text_color=s.TEXT_SECONDARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Check-in history",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=28, weight="bold"),
            text_color=s.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 0))

        filter_card = ctk.CTkFrame(
            self,
            fg_color=s.CARD_COLOR,
            corner_radius=0,
            border_width=1,
            border_color=s.LINE,
        )
        filter_card.pack(fill="x", padx=s.PADDING_LARGE, pady=(0, s.PADDING_MEDIUM))

        filter_inner = ctk.CTkFrame(filter_card, fg_color="transparent")
        filter_inner.pack(fill="x", padx=s.PADDING_MEDIUM, pady=s.PADDING_MEDIUM)

        ctk.CTkLabel(
            filter_inner,
            text="NAME",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=10),
            text_color=s.TEXT_SECONDARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, s.PADDING_MEDIUM))

        self.name_filter = ctk.CTkEntry(
            filter_inner,
            placeholder_text="Search",
            height=40,
            corner_radius=0,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
            border_width=1,
            border_color=s.LINE,
            fg_color=s.PAPER,
            text_color=s.INK,
        )
        self.name_filter.grid(row=1, column=0, sticky="ew", pady=(4, 0), padx=(0, s.PADDING_MEDIUM))
        self.name_filter.bind("<KeyRelease>", lambda _: self._refresh_log())

        ctk.CTkLabel(
            filter_inner,
            text="DATE  YYYY-MM-DD",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=10),
            text_color=s.TEXT_SECONDARY,
        ).grid(row=0, column=1, sticky="w")

        self.date_filter = ctk.CTkEntry(
            filter_inner,
            placeholder_text="2026-08-30",
            height=40,
            corner_radius=0,
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
            border_width=1,
            border_color=s.LINE,
            fg_color=s.PAPER,
            text_color=s.INK,
        )
        self.date_filter.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.date_filter.bind("<KeyRelease>", lambda _: self._refresh_log())

        filter_inner.columnconfigure(0, weight=1)
        filter_inner.columnconfigure(1, weight=1)

        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self.scroll_frame.pack(
            fill="both", expand=True, padx=s.PADDING_LARGE, pady=(0, s.PADDING_LARGE)
        )

        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="No check-ins yet.",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
            text_color=s.TEXT_SECONDARY,
        )

    def on_show(self) -> None:
        self._refresh_log()

    def on_hide(self) -> None:
        pass

    def _refresh_log(self) -> None:
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        records = db.get_attendance_log(
            self.name_filter.get(), self.date_filter.get()
        )

        if not records:
            self.empty_label = ctk.CTkLabel(
                self.scroll_frame,
                text="No records found.",
                font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=14),
                text_color=s.TEXT_SECONDARY,
            )
            self.empty_label.pack(pady=s.PADDING_LARGE)
            return

        for record in records:
            self._add_log_row(record)

    def _add_log_row(self, record: dict) -> None:
        row_card = ctk.CTkFrame(
            self.scroll_frame,
            fg_color=s.PAPER,
            corner_radius=0,
            border_width=1,
            border_color=s.LINE,
            height=76,
        )
        row_card.pack(fill="x", pady=(0, 8))
        row_card.pack_propagate(False)

        inner = ctk.CTkFrame(row_card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=s.PADDING_MEDIUM, pady=s.PADDING_SMALL)

        try:
            dt = datetime.fromisoformat(record["timestamp"])
            date_str = dt.strftime("%b %d, %Y")
            time_str = dt.strftime("%I:%M %p")
        except (ValueError, TypeError):
            date_str = record.get("timestamp", "")
            time_str = ""

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(
            top,
            text=record["employee_name"],
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=15, weight="bold"),
            text_color=s.TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            top,
            text="GRANTED",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=10, weight="bold"),
            text_color=s.INK,
            anchor="e",
        ).pack(side="right")

        ctk.CTkLabel(
            inner,
            text=f"{date_str}   {time_str}   MATCH {record['confidence']:.0%}",
            font=ctk.CTkFont(family=s.FONT_FAMILY[0], size=12),
            text_color=s.TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
