from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .codex_runner import CodexRunner
from .database import Database
from .security import UserContext, classify_prompt, user_from_request
from .settings import load_settings

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

settings = load_settings()
db = Database()
runner = CodexRunner(db, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.cleanup(settings.retention_days)
    yield


app = FastAPI(title="Home Assistant Codex Agent", version="0.1.5", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    mode: Literal["ask", "propose", "apply"] = "ask"
    approved: bool = False
    yolo: bool = False
    secret_access_approved: bool = False


class ImportAuthRequest(BaseModel):
    auth_json: str = Field(min_length=2, max_length=200_000)


def current_user(request: Request) -> UserContext:
    user = user_from_request(request)
    db.upsert_user(user.user_id, user.username, user.display_name, user.safe_id)
    return user


UserDep = Annotated[UserContext, Depends(current_user)]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def status(user: UserDep) -> dict:
    auth = runner.auth_status(user)
    ha_context = await runner.ha.context()
    return {
        "user": {
            "id": user.user_id,
            "username": user.username,
            "display_name": user.display_name,
        },
        "auth": auth,
        "settings": settings.__dict__,
        "home_assistant": ha_context,
        "runs": db.list_runs(user.user_id, limit=10),
    }


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

    auth = runner.auth_status(user)
    if not auth.get("configured"):
        raise HTTPException(status_code=401, detail="Codex is not configured for this user.")

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
            assessment,
            approved=payload.approved,
            yolo=payload.yolo,
            secret_access_approved=payload.secret_access_approved,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"run_id": run_id, "assessment": assessment.__dict__}


@app.get("/api/runs")
async def list_runs(user: UserDep) -> dict:
    return {"runs": db.list_runs(user.user_id)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, user: UserDep, after_event_id: int = 0) -> dict:
    run = db.get_run(run_id)
    if not run or run["user_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Run not found.")
    events = db.list_events(run_id, after_id=after_event_id)
    return {"run": run, "events": events}


@app.post("/api/maintenance/cleanup")
async def cleanup(user: UserDep) -> dict:
    _ = user
    return db.cleanup(settings.retention_days)
