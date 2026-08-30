"""SQLite storage for employees, static shifts, and work sessions."""

from __future__ import annotations

import pickle
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

from core.time_utils import format_hours, hours_between, hours_status, identify_shift

DB_PATH = Path(__file__).resolve().parent.parent / "bunkeratt.db"

DEFAULT_SHIFTS = [
    ("Day", "08:00", "16:00"),
    ("Evening", "16:00", "00:00"),
    ("Night", "20:00", "04:00"),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TEXT NOT NULL,
                shift_id INTEGER,
                FOREIGN KEY (shift_id) REFERENCES shifts(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                employee_name TEXT NOT NULL,
                work_date TEXT NOT NULL,
                clock_in TEXT NOT NULL,
                clock_out TEXT,
                hours REAL,
                confidence REAL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_employee
                ON work_sessions(employee_id, work_date);
            CREATE INDEX IF NOT EXISTS idx_sessions_open
                ON work_sessions(employee_id, clock_out);
            """
        )
        cols = _columns(conn, "employees")
        if "shift_id" not in cols:
            conn.execute("ALTER TABLE employees ADD COLUMN shift_id INTEGER")

        sess_cols = _columns(conn, "work_sessions")
        alters = {
            "shift_id": "INTEGER",
            "shift_name": "TEXT",
            "late": "INTEGER NOT NULL DEFAULT 0",
            "minutes_late": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, decl in alters.items():
            if col not in sess_cols:
                conn.execute(f"ALTER TABLE work_sessions ADD COLUMN {col} {decl}")

        existing = conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO shifts (name, start_time, end_time) VALUES (?, ?, ?)",
                DEFAULT_SHIFTS,
            )

        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            import os

            from core.auth import hash_password

            username = os.getenv("ADMIN_USERNAME", "admin")
            password = os.getenv("ADMIN_PASSWORD", "admin123")
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), datetime.now().isoformat()),
            )


def add_employee(
    employee_id: str,
    name: str,
    embedding: np.ndarray,
    shift_id: int | None = None,
) -> None:
    blob = pickle.dumps(embedding.astype(np.float32))
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO employees (employee_id, name, embedding, created_at, shift_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (employee_id.strip(), name.strip(), blob, now, shift_id),
        )


def list_employees() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.employee_id, e.name, e.created_at, e.shift_id,
                   s.name AS shift_name, s.start_time, s.end_time
            FROM employees e
            LEFT JOIN shifts s ON s.id = e.shift_id
            ORDER BY e.name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_passes() -> list[dict]:
    return list_employees()


def get_all_employees() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.employee_id, e.name, e.embedding, e.created_at, e.shift_id,
                   s.name AS shift_name, s.start_time, s.end_time
            FROM employees e
            LEFT JOIN shifts s ON s.id = e.shift_id
            ORDER BY e.name
            """
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "employee_id": row["employee_id"],
                "name": row["name"],
                "embedding": pickle.loads(row["embedding"]),
                "created_at": row["created_at"],
                "shift_id": row["shift_id"],
                "shift_name": row["shift_name"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
            }
        )
    return result


def employee_id_exists(employee_id: str, exclude_id: str | None = None) -> bool:
    sql = "SELECT 1 FROM employees WHERE employee_id = ?"
    params: list = [employee_id.strip()]
    if exclude_id:
        sql += " AND employee_id != ?"
        params.append(exclude_id.strip())
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return row is not None


def update_employee(
    employee_id: str,
    *,
    name: str,
    new_employee_id: str,
    shift_id: int | None,
    embedding: np.ndarray | None = None,
) -> dict | None:
    current = next((e for e in list_employees() if e["employee_id"] == employee_id.strip()), None)
    if current is None:
        return None
    next_id = new_employee_id.strip()
    next_name = name.strip()
    with get_connection() as conn:
        if embedding is not None:
            blob = pickle.dumps(embedding.astype(np.float32))
            conn.execute(
                """
                UPDATE employees
                SET employee_id = ?, name = ?, shift_id = ?, embedding = ?
                WHERE employee_id = ?
                """,
                (next_id, next_name, shift_id, blob, employee_id.strip()),
            )
        else:
            conn.execute(
                """
                UPDATE employees SET employee_id = ?, name = ?, shift_id = ?
                WHERE employee_id = ?
                """,
                (next_id, next_name, shift_id, employee_id.strip()),
            )
        conn.execute(
            """
            UPDATE work_sessions
            SET employee_id = ?, employee_name = ?
            WHERE employee_id = ?
            """,
            (next_id, next_name, employee_id.strip()),
        )
    return next((e for e in list_employees() if e["employee_id"] == next_id), None)


def delete_employee(employee_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM work_sessions WHERE employee_id = ?", (employee_id.strip(),))
        cur = conn.execute("DELETE FROM employees WHERE employee_id = ?", (employee_id.strip(),))
        return cur.rowcount > 0


def find_shift_session(employee_id: str, work_date: str, shift_id: int | None) -> dict | None:
    with get_connection() as conn:
        if shift_id is not None:
            row = conn.execute(
                """
                SELECT * FROM work_sessions
                WHERE employee_id = ? AND work_date = ? AND shift_id = ?
                ORDER BY clock_in DESC LIMIT 1
                """,
                (employee_id.strip(), work_date, shift_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM work_sessions
                WHERE employee_id = ? AND work_date = ?
                ORDER BY clock_in DESC LIMIT 1
                """,
                (employee_id.strip(), work_date),
            ).fetchone()
    return dict(row) if row else None


def list_shifts() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, start_time, end_time FROM shifts ORDER BY start_time, name"
        ).fetchall()
    return [dict(row) for row in rows]


def add_shift(name: str, start_time: str, end_time: str) -> dict:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO shifts (name, start_time, end_time) VALUES (?, ?, ?)",
            (name.strip(), start_time.strip(), end_time.strip()),
        )
        row = conn.execute(
            "SELECT id, name, start_time, end_time FROM shifts WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def get_open_session(employee_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM work_sessions
            WHERE employee_id = ? AND clock_out IS NULL
            ORDER BY clock_in DESC LIMIT 1
            """,
            (employee_id.strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_user(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    return dict(row) if row else None


def delete_shift(shift_id: int) -> bool:
    with get_connection() as conn:
        conn.execute("UPDATE employees SET shift_id = NULL WHERE shift_id = ?", (shift_id,))
        cur = conn.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
        return cur.rowcount > 0


def current_shift_state(employee: dict, now: datetime | None = None) -> tuple[dict | None, dict | None]:
    now = now or datetime.now()
    matched = identify_shift(now, list_shifts(), preferred_id=employee.get("shift_id"))
    work_date = matched["work_date"].isoformat() if matched else now.date().isoformat()
    shift_id = matched["shift"].get("id") if matched else None
    existing = find_shift_session(employee["employee_id"], work_date, shift_id)
    return matched, existing


def clock_in(employee: dict, confidence: float, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    matched, existing = current_shift_state(employee, now)
    if existing:
        return {
            **existing,
            "_blocked": True,
            "_reason": "already_in" if not existing.get("clock_out") else "already_this_shift",
        }
    work_date = matched["work_date"] if matched else now.date()
    shift = matched["shift"] if matched else {}
    late = bool(matched and matched["late"])
    minutes_late = int(matched["minutes_late"]) if matched else 0
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO work_sessions
                (employee_id, employee_name, work_date, clock_in, clock_out, hours, confidence,
                 created_at, shift_id, shift_name, late, minutes_late)
            VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee["employee_id"],
                employee["name"],
                work_date.isoformat(),
                now.isoformat(),
                float(confidence),
                now.isoformat(),
                shift.get("id"),
                shift.get("name"),
                1 if late else 0,
                minutes_late,
            ),
        )
        row = conn.execute(
            "SELECT * FROM work_sessions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def clock_out(session_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM work_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Session not found")
        if row["clock_out"]:
            return dict(row)
        started = datetime.fromisoformat(row["clock_in"])
        hours = round(hours_between(started, now), 4)
        conn.execute(
            "UPDATE work_sessions SET clock_out = ?, hours = ? WHERE id = ?",
            (now.isoformat(), hours, session_id),
        )
        updated = conn.execute(
            "SELECT * FROM work_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(updated)


def list_sessions(
    work_date: str = "",
    name: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    query = "SELECT * FROM work_sessions WHERE 1=1"
    params: list = []
    if date_from.strip() and date_to.strip():
        query += " AND work_date >= ? AND work_date <= ?"
        params.extend([date_from.strip(), date_to.strip()])
    elif work_date.strip():
        query += " AND work_date = ?"
        params.append(work_date.strip())
    if name.strip():
        query += " AND employee_name LIKE ?"
        params.append(f"%{name.strip()}%")
    query += " ORDER BY work_date DESC, clock_in DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_session_out(dict(row)) for row in rows]


def _session_out(row: dict) -> dict:
    in_progress = not row.get("clock_out")
    hours = row.get("hours")
    if in_progress and row.get("clock_in"):
        started = datetime.fromisoformat(row["clock_in"])
        live = round(hours_between(started, datetime.now()), 4)
        return {
            **row,
            "hours": live,
            "in_progress": True,
            "hours_formatted": "IN PROGRESS",
            "hours_status": "open",
            "late": bool(row.get("late")),
            "minutes_late": int(row.get("minutes_late") or 0),
            "late_label": _late_label(row),
        }
    hrs = float(hours) if hours is not None else None
    return {
        **row,
        "in_progress": False,
        "hours_formatted": format_hours(hrs),
        "hours_status": hours_status(hrs),
        "late": bool(row.get("late")),
        "minutes_late": int(row.get("minutes_late") or 0),
        "late_label": _late_label(row),
    }


def _late_label(row: dict) -> str:
    if not row.get("late"):
        return "On time"
    mins = int(row.get("minutes_late") or 0)
    return f"Late {mins} min"
