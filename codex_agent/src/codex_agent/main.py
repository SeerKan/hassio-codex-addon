from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from . import __version__
from .codex_runner import CodexRunner
from .database import Database, utcnow
from .event_view import display_events
from .models import CODEX_MODEL_IDS, CODEX_MODEL_OPTIONS, DEFAULT_CODEX_MODEL, normalize_model
from .security import UserContext, classify_prompt, user_from_request
from .settings import load_settings

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
CACHE_VERSION_COOKIE = "codex_agent_asset_version"

settings = load_settings()
db = Database()
runner = CodexRunner(db, settings)
MODE_VALUES = {"ask", "propose", "apply"}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_MARKDOWN_CHARS = 200_000
MAX_ATTACHMENTS_PER_RUN = 8
ATTACHMENT_PREVIEW_CHARS = 600
UPLOAD_CHUNK_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.cleanup(settings.retention_days)
    yield


app = FastAPI(title="Home Assistant Codex Agent", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_cache_sidebar_assets(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = (
        "no-store, no-cache, max-age=0, s-maxage=0, must-revalidate, proxy-revalidate, private"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["X-Accel-Expires"] = "0"
    response.headers["Vary"] = "Cookie, Accept-Encoding"
    if _is_html_request(request) and request.cookies.get(CACHE_VERSION_COOKIE) != __version__:
        response.set_cookie(
            CACHE_VERSION_COOKIE,
            __version__,
            httponly=False,
            max_age=31_536_000,
            path="/",
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def _is_html_request(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    path = request.url.path
    return (
        "text/html" in accept
        and not path.startswith("/api/")
        and not path.startswith("/static/")
    )


def _default_model() -> str:
    return settings.codex_model if settings.codex_model in CODEX_MODEL_IDS else DEFAULT_CODEX_MODEL


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    mode: Literal["ask", "propose", "apply"] = "ask"
    model: str | None = Field(default=None, max_length=80)
    approved: bool = False
    yolo: bool = False
    secret_access_approved: bool = False
    session_id: str | None = None
    create_new_session: bool = False
    attachment_ids: list[str] = Field(default_factory=list, max_length=MAX_ATTACHMENTS_PER_RUN)


class ImportAuthRequest(BaseModel):
    auth_json: str = Field(min_length=2, max_length=200_000)


class PreferencesRequest(BaseModel):
    mode: Literal["ask", "propose", "apply"] | None = None
    model: str | None = Field(default=None, max_length=80)


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=128)


def current_user(request: Request) -> UserContext:
    user = user_from_request(request)
    db.upsert_user(user.user_id, user.username, user.display_name, user.safe_id)
    return user


UserDep = Annotated[UserContext, Depends(current_user)]


@app.get("/")
async def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    html = html.replace("__APP_VERSION__", __version__)
    html = html.replace("__APP_STYLES__", styles.replace("</style", "<\\/style"))
    html = html.replace("__APP_SCRIPT__", script.replace("</script", "<\\/script"))
    html = html.replace("__MODEL_OPTIONS__", _model_options_html())
    return HTMLResponse(html)


def _model_options_html() -> str:
    return "\n".join(
        (
            f'              <option value="{escape(model["id"], quote=True)}"'
            f' title="{escape(model.get("description", ""), quote=True)}"'
            f"{' selected' if model['id'] == DEFAULT_CODEX_MODEL else ''}>"
            f'{escape(model.get("label", model["id"]))}</option>'
        )
        for model in CODEX_MODEL_OPTIONS[:10]
    )


def _preferences_key(user: UserContext) -> str:
    return f"user_preferences:{user.user_id}"


def _user_preferences(user: UserContext) -> dict[str, str | bool]:
    raw = db.get_state(_preferences_key(user)) or {}
    mode = raw.get("mode") if raw.get("mode") in MODE_VALUES else ""
    model = normalize_model(raw.get("model")) or ""
    if model not in CODEX_MODEL_IDS:
        model = ""
    return {
        "mode": mode,
        "model": model,
        "persisted": bool(raw),
    }


def _save_user_preferences(
    user: UserContext,
    *,
    mode: str | None = None,
    model: str | None = None,
) -> dict[str, str | bool]:
    preferences = _user_preferences(user)
    if mode is not None:
        if mode not in MODE_VALUES:
            raise HTTPException(status_code=400, detail=f"Unsupported mode: {mode}")
        preferences["mode"] = mode
    if model is not None:
        normalized_model = normalize_model(model) or ""
        if normalized_model and normalized_model not in CODEX_MODEL_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported Codex model: {normalized_model}",
            )
        preferences["model"] = normalized_model
    db.set_state(_preferences_key(user), preferences)
    return _user_preferences(user)


def _safe_filename(filename: str | None) -> str:
    value = Path(filename or "attachment").name.strip()
    return value or "attachment"


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if not suffix or len(suffix) > 16:
        return ".upload"
    safe = "".join(character for character in suffix if character.isalnum() or character == ".")
    return safe or ".upload"


def _clean_attachment_ids(attachment_ids: list[str]) -> list[str]:
    cleaned = [str(attachment_id).strip() for attachment_id in attachment_ids if attachment_id]
    cleaned = list(dict.fromkeys(cleaned))
    if len(cleaned) > MAX_ATTACHMENTS_PER_RUN:
        raise HTTPException(
            status_code=400,
            detail=f"Attach at most {MAX_ATTACHMENTS_PER_RUN} files to one message.",
        )
    if any(len(attachment_id) > 80 for attachment_id in cleaned):
        raise HTTPException(status_code=400, detail="Invalid attachment id.")
    return cleaned


async def _store_upload_temporarily(upload: StarletteUploadFile) -> tuple[Path, int]:
    filename = _safe_filename(upload.filename)
    total = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=_safe_suffix(filename)) as temp_file:
            temp_path = Path(temp_file.name)
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Attachment is larger than the 25 MB limit.",
                    )
                temp_file.write(chunk)
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise

    if temp_path is None:
        raise HTTPException(status_code=400, detail="Could not prepare attachment upload.")
    if total == 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Attachment is empty.")
    return temp_path, total


def _convert_attachment_with_markitdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError("MarkItDown is not installed in this add-on image.") from exc

    converter = MarkItDown(enable_plugins=False)
    convert = getattr(converter, "convert_local", converter.convert)
    result = convert(str(path))
    markdown = getattr(result, "text_content", None) or getattr(result, "markdown", None)
    if markdown is None:
        markdown = str(result)
    markdown = str(markdown).strip()
    if not markdown:
        raise ValueError("MarkItDown did not extract any readable markdown from this file.")
    if len(markdown) > MAX_ATTACHMENT_MARKDOWN_CHARS:
        markdown = (
            markdown[: MAX_ATTACHMENT_MARKDOWN_CHARS - 96].rstrip()
            + "\n\n[Attachment markdown truncated by the add-on before sending to Codex.]"
        )
    return markdown


def _attachment_response(record: dict) -> dict:
    markdown = record.get("markdown", "")
    return {
        "id": record["id"],
        "filename": record["filename"],
        "content_type": record["content_type"],
        "size_bytes": record["size_bytes"],
        "markdown_chars": len(markdown),
        "preview": markdown[:ATTACHMENT_PREVIEW_CHARS],
        "created_at": record["created_at"],
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def status(user: UserDep) -> dict:
    auth = runner.auth_status(user)
    ha_context = await runner.ha.context()
    sessions = db.list_sessions(user.user_id, limit=40)
    active_session_id = sessions[0]["id"] if sessions else None
    recent_runs = db.list_runs(user.user_id, limit=10, session_id=active_session_id)
    return {
        "user": {
            "id": user.user_id,
            "username": user.username,
            "display_name": user.display_name,
        },
        "auth": auth,
        "settings": settings.__dict__,
        "app_version": __version__,
        "models": {
            "default": _default_model(),
            "options": CODEX_MODEL_OPTIONS[:10],
        },
        "preferences": _user_preferences(user),
        "home_assistant": ha_context,
        "active_session_id": active_session_id,
        "runs_session_id": active_session_id,
        "sessions": sessions,
        "runs": recent_runs,
    }


@app.post("/api/preferences")
async def save_preferences(payload: PreferencesRequest, user: UserDep) -> dict:
    preferences = _save_user_preferences(user, mode=payload.mode, model=payload.model)
    return {"preferences": preferences}


@app.post("/api/attachments")
async def create_attachment(request: Request, user: UserDep) -> dict:
    try:
        form = await request.form(max_files=1, max_fields=4)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read the uploaded file. Make sure it is sent as multipart form data.",
        ) from exc

    upload = form.get("file")
    if not isinstance(upload, StarletteUploadFile):
        raise HTTPException(
            status_code=400,
            detail="Upload a file using the form field named file.",
        )

    filename = _safe_filename(upload.filename)
    temp_path, size_bytes = await _store_upload_temporarily(upload)
    try:
        markdown = _convert_attachment_with_markitdown(temp_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not convert {filename} with MarkItDown: {exc}",
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    record = {
        "id": str(uuid.uuid4()),
        "user_id": user.user_id,
        "filename": filename,
        "content_type": upload.content_type or "application/octet-stream",
        "size_bytes": size_bytes,
        "markdown": markdown,
        "created_at": utcnow(),
    }
    db.create_attachment(record)
    return {"attachment": _attachment_response(record)}


@app.delete("/api/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, user: UserDep) -> dict[str, bool]:
    db.delete_attachment(user.user_id, attachment_id)
    return {"deleted": True}


@app.post("/api/auth/start")
async def start_auth(user: UserDep) -> dict[str, str]:
    try:
        job_id = runner.start_login(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"job_id": job_id}


@app.get("/api/auth/jobs/{job_id}")
async def auth_job(job_id: str, user: UserDep) -> dict:
    job = db.get_auth_job(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Login job not found.")
    view = runner.auth_job_view(job)
    view["auth"] = runner.auth_status(user)
    return view


@app.post("/api/auth/import")
async def import_auth(payload: ImportAuthRequest, user: UserDep) -> dict:
    try:
        return runner.import_auth_json(user, payload.auth_json)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs")
async def create_run(payload: RunRequest, user: UserDep) -> dict:
    if payload.yolo and not settings.allow_yolo_mode:
        raise HTTPException(status_code=400, detail="Full-auto mode is disabled in add-on options.")

    selected_model = normalize_model(payload.model) or _default_model()
    if selected_model not in CODEX_MODEL_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported Codex model: {selected_model}")
    _save_user_preferences(user, mode=payload.mode, model=selected_model)

    auth = runner.auth_status(user)
    if not auth.get("configured"):
        raise HTTPException(status_code=401, detail="Codex is not configured for this user.")

    attachment_ids = _clean_attachment_ids(payload.attachment_ids)
    attachments = db.get_attachments(user.user_id, attachment_ids)
    if len(attachments) != len(attachment_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more attachments were not found. Upload them again and retry.",
        )

    assessment = classify_prompt(
        payload.prompt,
        payload.mode,
        yolo=payload.yolo,
        secret_access_approved=payload.secret_access_approved,
        require_approval_for_secrets=settings.require_approval_for_secrets,
    )
    if assessment.approval_required and not payload.approved:
        raise HTTPException(
            status_code=409,
            detail={
                "approval_required": True,
                "assessment": assessment.__dict__,
            },
        )

    try:
        run_id = await runner.start_run(
            user,
            payload.prompt,
            payload.mode,
            selected_model,
            None if payload.create_new_session else payload.session_id,
            assessment,
            create_new_session=payload.create_new_session,
            approved=payload.approved,
            yolo=payload.yolo,
            secret_access_approved=payload.secret_access_approved,
            attachments=attachments,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    run = db.get_run(run_id)
    return {
        "run_id": run_id,
        "session_id": run["session_id"] if run else None,
        "assessment": assessment.__dict__,
    }


@app.get("/api/runs")
async def list_runs(
    user: UserDep,
    session_id: str | None = None,
    limit: int = 100,
    order: Literal["asc", "desc"] = "desc",
) -> dict:
    safe_limit = max(1, min(limit, 200))
    return {
        "runs": db.list_runs(
            user.user_id,
            limit=safe_limit,
            session_id=session_id,
            order=order,
        )
    }


@app.get("/api/sessions")
async def list_sessions(user: UserDep) -> dict:
    return {"sessions": db.list_sessions(user.user_id)}


@app.post("/api/sessions")
async def create_session(payload: SessionCreateRequest, user: UserDep) -> dict:
    title = payload.title.strip() if payload.title else "Session"
    if not title:
        title = "Session"
    session_id = db.create_session(user.user_id, title)
    return {"session_id": session_id}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, user: UserDep, after_event_id: int = 0) -> dict:
    run = db.get_run(run_id)
    if not run or run["user_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Run not found.")
    events = db.list_events(run_id, after_id=after_event_id)
    return {"run": run, "events": display_events(events)}


@app.post("/api/maintenance/cleanup")
async def cleanup(user: UserDep) -> dict:
    _ = user
    return db.cleanup(settings.retention_days)
