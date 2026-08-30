"""Shift day and hours — overnight stays on the same work date."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Optional


def parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour % 24, minute)


def is_overnight(start_hhmm: str, end_hhmm: str) -> bool:
    return parse_hhmm(end_hhmm) <= parse_hhmm(start_hhmm)


def work_date_for(now: datetime, start_hhmm: str | None, end_hhmm: str | None) -> date:
    """Calendar date of the shift. After midnight on an overnight shift still counts as yesterday."""
    if not start_hhmm or not end_hhmm:
        return now.date()
    if is_overnight(start_hhmm, end_hhmm) and now.time() < parse_hhmm(end_hhmm):
        return now.date() - timedelta(days=1)
    return now.date()


def hours_between(clock_in: datetime, clock_out: datetime) -> float:
    delta = clock_out - clock_in
    return max(0.0, delta.total_seconds() / 3600.0)


def hours_status(hours: Optional[float]) -> str:
    if hours is None:
        return "open"
    if hours < 8:
        return "under"
    if round(hours, 2) == 8.00:
        return "exact"
    return "over"


def format_hours(hours: Optional[float]) -> str:
    if hours is None:
        return "—"
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h}:{m:02d}"


def shift_window(now: datetime, start_hhmm: str, end_hhmm: str) -> tuple[datetime, datetime, date]:
    """Start/end datetimes for the shift occurrence that covers `now` (overnight-safe)."""
    wd = work_date_for(now, start_hhmm, end_hhmm)
    start_dt = datetime.combine(wd, parse_hhmm(start_hhmm))
    end_t = parse_hhmm(end_hhmm)
    if is_overnight(start_hhmm, end_hhmm) or end_t == time(0, 0):
        end_day = wd + timedelta(days=1)
        end_dt = datetime.combine(end_day, end_t)
    else:
        end_dt = datetime.combine(wd, end_t)
    return start_dt, end_dt, wd


def identify_shift(
    now: datetime,
    shifts: list[dict],
    preferred_id: int | None = None,
) -> dict | None:
    """Pick the shift window that contains now. Example: 16:30 → 16:00 shift, late."""
    if not shifts:
        return None

    scored: list[tuple] = []
    for shift in shifts:
        start_dt, end_dt, wd = shift_window(now, shift["start_time"], shift["end_time"])
        in_window = start_dt <= now < end_dt
        minutes_late = max(0, int((now - start_dt).total_seconds() // 60))
        scored.append((in_window, start_dt, end_dt, wd, minutes_late, shift))

    in_windows = [s for s in scored if s[0]]
    chosen = None
    if preferred_id is not None:
        for item in in_windows:
            if item[5].get("id") == preferred_id:
                chosen = item
                break
        if chosen is None:
            for item in scored:
                if item[5].get("id") == preferred_id and item[1] <= now:
                    # Assigned shift already started; still attach even if past end (very late).
                    start_dt, end_dt, wd, minutes_late, shift = item[1], item[2], item[3], item[4], item[5]
                    if now < end_dt + timedelta(hours=6):
                        chosen = item
                        break
    if chosen is None and in_windows:
        chosen = max(in_windows, key=lambda s: s[1])
    if chosen is None:
        past = [s for s in scored if s[1] <= now]
        if past:
            chosen = max(past, key=lambda s: s[1])
        else:
            chosen = min(scored, key=lambda s: abs((s[1] - now).total_seconds()))

    _in, start_dt, end_dt, wd, minutes_late, shift = chosen
    late = minutes_late >= 1
    return {
        "shift": shift,
        "work_date": wd,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "late": late,
        "minutes_late": minutes_late if late else 0,
    }


def period_range(period: str, anchor: date) -> tuple[date, date]:
    period = (period or "daily").lower()
    if period == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == "monthly":
        start = anchor.replace(day=1)
        if start.month == 12:
            nxt = start.replace(year=start.year + 1, month=1, day=1)
        else:
            nxt = start.replace(month=start.month + 1, day=1)
        return start, nxt - timedelta(days=1)
    return anchor, anchor
