"""Access Pass web server."""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import db, reports
from core.auth import create_token, hash_password, read_token, verify_password
from core.face_engine import MATCH_THRESHOLD, FaceEngine
from core.face_quality import validate_enrollment_face
from core.images import decode_image_b64

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"
CAPTURES_REQUIRED = 5

_engine = FaceEngine()
_enroll_engine = FaceEngine(det_size=(640, 640), min_det_score=0.18)
_engine_lock = threading.Lock()


def get_engine() -> FaceEngine:
    with _engine_lock:
        if not _engine.is_ready:
            if not _engine.initialize():
                raise HTTPException(
                    status_code=503,
                    detail=_engine.load_error or "Face engine failed to load",
                )
        return _engine


def get_enroll_engine() -> FaceEngine:
    with _engine_lock:
        if not _enroll_engine.is_ready:
            if not _enroll_engine.initialize():
                raise HTTPException(
                    status_code=503,
                    detail=_enroll_engine.load_error or "Face engine failed to load",
                )
        return _enroll_engine


def require_admin(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    elif token:
        raw = token.strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Admin login required")
    user = read_token(raw)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return user


def require_super(user: dict = Depends(require_admin)) -> dict:
    if user.get("role") != "super":
        raise HTTPException(status_code=403, detail="Super admin only")
    return user


def identify_frame(image_b64: str) -> dict:
    frame = decode_image_b64(image_b64)
    engine = get_engine()
    faces = engine.detect_faces(frame)
    if len(faces) == 0:
        return {"status": "no_face"}
    if len(faces) > 1:
        return {"status": "multiple_faces"}
    employees = db.get_all_employees()
    if not employees:
        return {"status": "unrecognized"}
    match = engine.find_best_match(faces[0].embedding, employees, MATCH_THRESHOLD)
    if match is None:
        return {"status": "unrecognized"}
    employee, confidence = match
    matched_shift, existing = db.current_shift_state(employee)
    open_session = existing if existing and not existing.get("clock_out") else None
    out_session = db._session_out(open_session) if open_session else (
        db._session_out(existing) if existing else None
    )
    shift_name = None
    if matched_shift and matched_shift.get("shift"):
        shift_name = matched_shift["shift"].get("name")
    if out_session and out_session.get("shift_name"):
        shift_name = out_session.get("shift_name")
    return {
        "status": "matched",
        "name": employee["name"],
        "employee_id": employee["employee_id"],
        "confidence": round(float(confidence), 3),
        "shift_name": shift_name or employee.get("shift_name"),
        "clocked_in": open_session is not None,
        "already_this_shift": bool(existing and existing.get("clock_out")),
        "session": out_session,
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()

    def _warm():
        try:
            get_engine()
            get_enroll_engine()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="ModelWarmup").start()
    yield


app = FastAPI(title="ACCESS PASS", version="2.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CaptureBody(BaseModel):
    image_b64: str = Field(min_length=32)
    previous_b64: str | None = None


class EnrollBody(BaseModel):
    employee_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    shift_id: int | None = None
    images_b64: list[str] = Field(min_length=CAPTURES_REQUIRED, max_length=12)


class EmployeeUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    new_employee_id: str = Field(min_length=1, max_length=64)
    shift_id: int | None = None
    images_b64: list[str] | None = None


class ShiftBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    start_time: str
    end_time: str


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminCreateBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class AdminUpdateBody(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=6, max_length=128)


class SuperPasswordBody(BaseModel):
    password: str = Field(min_length=6, max_length=128)


def _hhmm(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Time must be HH:MM")
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


def _single_enroll_face(frame, engine: FaceEngine):
    faces = engine.detect_faces(frame)
    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected — look at the camera")
    if len(faces) > 1:
        raise HTTPException(status_code=400, detail="Multiple faces — only one person")
    face = faces[0]
    try:
        validate_enrollment_face(frame, face.bbox, face.confidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return face


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "app": "ACCESS PASS",
        "models_ready": _engine.is_ready,
        "models_message": None if _engine.is_ready else (_engine.load_error or "loading"),
    }


@app.post("/api/v1/auth/login")
def login(body: LoginBody):
    db.init_db()
    user = db.get_user(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    role = user.get("role") or "admin"
    return {
        "token": create_token(user["username"], role),
        "username": user["username"],
        "role": role,
    }


@app.get("/api/v1/auth/me")
def auth_me(user: dict = Depends(require_admin)):
    return {"ok": True, "username": user["username"], "role": user["role"]}


@app.get("/api/v1/staff")
def list_staff(_: dict = Depends(require_super)):
    db.init_db()
    return {"admins_used": db.count_admins(), "admins_max": db.MAX_ADMINS, "users": db.list_users()}


@app.post("/api/v1/staff")
def create_staff(body: AdminCreateBody, _: dict = Depends(require_super)):
    db.init_db()
    if db.get_user(body.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    try:
        return db.add_admin(body.username, hash_password(body.password))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/v1/staff/me")
def update_super_password(body: SuperPasswordBody, user: dict = Depends(require_super)):
    db.init_db()
    db.set_super_password(hash_password(body.password))
    return {"ok": True, "username": user["username"]}


@app.patch("/api/v1/staff/{user_id}")
def update_staff(user_id: int, body: AdminUpdateBody, _: dict = Depends(require_super)):
    db.init_db()
    target = db.get_user_by_id(user_id)
    if not target or target.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Admin not found")
    if body.username:
        clash = db.get_user(body.username)
        if clash and clash["id"] != user_id:
            raise HTTPException(status_code=409, detail="Username already exists")
    pwd = hash_password(body.password) if body.password else None
    updated = db.update_admin(user_id, username=body.username, password_hash=pwd)
    if not updated:
        raise HTTPException(status_code=404, detail="Admin not found")
    return updated


@app.delete("/api/v1/staff/{user_id}")
def remove_staff(user_id: int, _: dict = Depends(require_super)):
    db.init_db()
    if not db.delete_admin(user_id):
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"ok": True}


@app.post("/api/v1/captures/validate")
def validate_capture(body: CaptureBody, _: str = Depends(require_admin)):
    engine = get_enroll_engine()
    frame = decode_image_b64(body.image_b64)
    face = _single_enroll_face(frame, engine)
    return {"ok": True, "message": "Good capture.", "confidence": round(face.confidence, 3)}


@app.get("/api/v1/shifts")
def get_shifts(_: str = Depends(require_admin)):
    db.init_db()
    return db.list_shifts()


@app.post("/api/v1/shifts")
def create_shift(body: ShiftBody, _: str = Depends(require_admin)):
    db.init_db()
    try:
        return db.add_shift(body.name, _hhmm(body.start_time), _hhmm(body.end_time))
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Shift name already exists") from exc


@app.delete("/api/v1/shifts/{shift_id}")
def remove_shift(shift_id: int, _: str = Depends(require_admin)):
    db.init_db()
    if not db.delete_shift(shift_id):
        raise HTTPException(status_code=404, detail="Shift not found")
    return {"ok": True}


@app.get("/api/v1/passes")
def list_passes(_: str = Depends(require_admin)):
    db.init_db()
    return db.list_employees()


@app.post("/api/v1/passes/enroll")
def enroll_pass(body: EnrollBody, _: str = Depends(require_admin)):
    db.init_db()
    eid = body.employee_id.strip()
    if db.employee_id_exists(eid):
        raise HTTPException(status_code=409, detail="Employee ID already exists")

    avg = FaceEngine.robust_average_embeddings(_embeddings_from_images(body.images_b64))
    db.add_employee(eid, body.name.strip(), avg, shift_id=body.shift_id)
    created = next((p for p in db.list_employees() if p["employee_id"] == eid), None)
    if not created:
        raise HTTPException(status_code=500, detail="Enrollment failed")
    return created


def _embeddings_from_images(images_b64: list[str]) -> list:
    engine = get_enroll_engine()
    embeddings = []
    for i, img in enumerate(images_b64):
        frame = decode_image_b64(img)
        try:
            face = _single_enroll_face(frame, engine)
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=f"Capture {i + 1}: {exc.detail}") from exc
        embeddings.append(face.embedding)
    return embeddings


@app.patch("/api/v1/passes/{employee_id}")
def update_pass(employee_id: str, body: EmployeeUpdate, _: str = Depends(require_admin)):
    db.init_db()
    new_id = body.new_employee_id.strip()
    if db.employee_id_exists(new_id, exclude_id=employee_id):
        raise HTTPException(status_code=409, detail="Employee ID already exists")
    embedding = None
    if body.images_b64:
        if len(body.images_b64) < CAPTURES_REQUIRED:
            raise HTTPException(status_code=400, detail=f"Need {CAPTURES_REQUIRED} captures to replace the face")
        embedding = FaceEngine.robust_average_embeddings(_embeddings_from_images(body.images_b64))
    updated = db.update_employee(
        employee_id,
        name=body.name.strip(),
        new_employee_id=new_id,
        shift_id=body.shift_id,
        embedding=embedding,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Employee not found")
    return updated


@app.delete("/api/v1/passes/{employee_id}")
def remove_pass(employee_id: str, _: str = Depends(require_admin)):
    db.init_db()
    if not db.delete_employee(employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"ok": True}


@app.post("/api/v1/identify")
def identify(body: CaptureBody):
    db.init_db()
    return identify_frame(body.image_b64)


@app.post("/api/v1/clock-in")
def clock_in(body: CaptureBody):
    db.init_db()
    result = identify_frame(body.image_b64)
    if result["status"] != "matched":
        return result
    if result.get("clocked_in"):
        return {**result, "action": "already_in", "message": f"Hi {result['name']}, you are already clocked in."}
    if result.get("already_this_shift"):
        shift = result.get("shift_name") or "this"
        return {
            **result,
            "action": "already_this_shift",
            "message": f"Hi {result['name']}, you already clocked in for the {shift} shift.",
        }
    employee = next(
        e for e in db.get_all_employees() if e["employee_id"] == result["employee_id"]
    )
    session = db.clock_in(employee, result["confidence"])
    if session.get("_blocked"):
        reason = session.get("_reason")
        viewed = db._session_out(session)
        if reason == "already_in":
            return {**result, "action": "already_in", "session": viewed, "message": f"Hi {result['name']}, you are already clocked in."}
        shift = viewed.get("shift_name") or "this"
        return {
            **result,
            "action": "already_this_shift",
            "session": viewed,
            "message": f"Hi {result['name']}, you already clocked in for the {shift} shift.",
        }
    viewed = db._session_out(session)
    late_bit = ""
    if viewed.get("late"):
        late_bit = f" You are {viewed['minutes_late']} minutes late."
    shift_bit = f" {viewed.get('shift_name')} shift." if viewed.get("shift_name") else ""
    return {
        **result,
        "clocked_in": True,
        "action": "clocked_in",
        "session": viewed,
        "shift_name": viewed.get("shift_name"),
        "late": viewed.get("late"),
        "message": f"Hi {result['name']}, you are clocked in.{shift_bit}{late_bit}",
    }


@app.post("/api/v1/clock-out")
def clock_out(body: CaptureBody):
    db.init_db()
    result = identify_frame(body.image_b64)
    if result["status"] != "matched":
        return result
    session = db.get_open_session(result["employee_id"])
    if session is None:
        return {
            **result,
            "action": "not_in",
            "message": f"Hi {result['name']}, you are not clocked in.",
        }
    closed = db.clock_out(session["id"])
    return {
        **result,
        "clocked_in": False,
        "action": "clocked_out",
        "session": db._session_out(closed),
        "message": f"Hi {result['name']}, you are clocked out.",
        "prompt": f"Hi {result['name']}, are you ready to clock out?",
    }


@app.get("/api/v1/reports")
def get_reports(
    work_date: str = Query(default=""),
    period: str = Query(default="daily"),
    _: str = Depends(require_admin),
):
    rows, start, end, kind = reports.report_rows(period, work_date)
    return {"period": kind, "date_from": start, "date_to": end, "rows": rows}


@app.get("/api/v1/reports/excel")
def export_excel(
    work_date: str = Query(default=""),
    period: str = Query(default="daily"),
    _: str = Depends(require_admin),
):
    start, end, kind = reports.resolve_period(period, work_date)
    data = reports.build_excel(period, work_date)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="access-pass-{kind}-{start}-to-{end}.xlsx"'},
    )


@app.get("/api/v1/reports/pdf")
def export_pdf(
    work_date: str = Query(default=""),
    period: str = Query(default="daily"),
    _: str = Depends(require_admin),
):
    start, end, kind = reports.resolve_period(period, work_date)
    data = reports.build_pdf(period, work_date)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="access-pass-{kind}-{start}-to-{end}.pdf"'},
    )


if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def landing():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/employee")
    def employee_page():
        return FileResponse(WEB_DIR / "employee.html")

    @app.get("/admin")
    def admin_page():
        return FileResponse(WEB_DIR / "admin.html")
