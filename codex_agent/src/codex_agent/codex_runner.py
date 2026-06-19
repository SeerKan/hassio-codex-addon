from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .database import Database, utcnow
from .ha_client import HomeAssistantClient, supervisor_token
from .security import RiskAssessment, UserContext
from .settings import DATA_DIR, Settings
from .snapshot import collect_snapshot, diff_snapshots

USERS_DIR = DATA_DIR / "users"
WORKSPACE = Path("/homeassistant")
MAPPED_PATHS = (
    Path("/homeassistant"),
    Path("/config"),
    Path("/addon_configs"),
    Path("/addons"),
    Path("/share"),
    Path("/media"),
    Path("/ssl"),
)
LOCAL_CONTEXT_FILES = (
    Path("/homeassistant/.storage/lovelace"),
    Path("/homeassistant/.storage/lovelace_dashboards"),
    Path("/homeassistant/ui-lovelace.yaml"),
)
MANAGED_CODEX_CONFIG = 'cli_auth_credentials_store = "file"\n'
FIRST_CONFIG_BACKUP_STATE = "first_configuration_change_backup"
LEGACY_FIRST_BACKUP_STATE = "first_change_backup"
ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
DEVICE_URL_RE = re.compile(r"https://[^\s]+")
DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,}\b")
TITLE_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
TITLE_STOP_WORDS = {
    "about",
    "again",
    "all",
    "also",
    "and",
    "any",
    "are",
    "ask",
    "but",
    "couple",
    "can",
    "change",
    "check",
    "codex",
    "could",
    "create",
    "does",
    "for",
    "from",
    "have",
    "home",
    "assistant",
    "how",
    "into",
    "just",
    "like",
    "make",
    "max",
    "need",
    "off",
    "one",
    "only",
    "now",
    "please",
    "second",
    "show",
    "should",
    "since",
    "something",
    "tell",
    "that",
    "the",
    "then",
    "there",
    "this",
    "use",
    "used",
    "want",
    "what",
    "when",
    "will",
    "with",
    "would",
    "you",
}
TITLE_TOKEN_ALIASES = {
    "sceen": "scenes",
    "sceens": "scenes",
    "screenes": "scenes",
}
TITLE_DOMAIN_WORDS = {
    "automation",
    "automations",
    "camera",
    "card",
    "dashboard",
    "entity",
    "entities",
    "light",
    "lights",
    "scene",
    "scenes",
    "script",
    "scripts",
    "sensor",
    "sensors",
    "switch",
    "thermostat",
}


class CodexRunner:
    SESSION_CONTEXT_LIMIT = 8
    SESSION_TITLE_MAX = 64
    SESSION_CONTEXT_MAX_CHARS = 2800

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.ha = HomeAssistantClient()

    def codex_home_for(self, user: UserContext) -> Path:
        return USERS_DIR / user.safe_id / "codex_home"

    def ensure_user_home(self, user: UserContext) -> Path:
        home = self.codex_home_for(user)
        home.mkdir(parents=True, exist_ok=True)
        config = home / "config.toml"
        if not config.exists() or config.read_text(encoding="utf-8") != MANAGED_CODEX_CONFIG:
            config.write_text(MANAGED_CODEX_CONFIG, encoding="utf-8")
            config.chmod(0o600)
        return home

    def auth_status(self, user: UserContext) -> dict[str, Any]:
        home = self.ensure_user_home(user)
        auth_file = home / "auth.json"
        status = {"configured": auth_file.exists(), "auth_file": str(auth_file)}
        if auth_file.exists():
            try:
                raw = json.loads(auth_file.read_text(encoding="utf-8"))
                self._validate_auth_json(raw)
                status["auth_mode"] = raw.get("auth_mode", "unknown")
                status["last_refresh"] = raw.get("last_refresh")
            except json.JSONDecodeError:
                status["configured"] = False
                status["error"] = "auth.json is not valid JSON"
            except ValueError as exc:
                status["configured"] = False
                status["error"] = str(exc)
        return status

    def import_auth_json(self, user: UserContext, content: str) -> dict[str, Any]:
        parsed = json.loads(content)
        self._validate_auth_json(parsed)
        home = self.ensure_user_home(user)
        auth_file = home / "auth.json"
        auth_file.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        auth_file.chmod(0o600)
        return self.auth_status(user)

    def start_login(self, user: UserContext) -> str:
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI is not installed in this image.")
        home = self.ensure_user_home(user)
        job_id = str(uuid.uuid4())
        self.db.create_auth_job(job_id, user.user_id)
        thread = threading.Thread(
            target=self._run_login_process,
            args=(job_id, home),
            name=f"codex-login-{job_id}",
            daemon=True,
        )
        thread.start()
        return job_id

    def _run_login_process(self, job_id: str, home: Path) -> None:
        env = self._env(home)
        command = ["codex", "login", "--device-auth"]
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.db.append_auth_output(job_id, clean_terminal_text(line))
            exit_code = proc.wait()
            self.db.finish_auth_job(job_id, "completed" if exit_code == 0 else "failed", exit_code)
        except Exception as exc:
            self.db.append_auth_output(job_id, f"\nLogin process failed: {exc}\n")
            self.db.finish_auth_job(job_id, "failed", None)

    def auth_job_view(self, job: dict[str, Any]) -> dict[str, Any]:
        output = clean_terminal_text(job.get("output", ""))
        return {
            **job,
            "output": output,
            "login_url": self._first_match(DEVICE_URL_RE, output),
            "device_code": self._first_match(DEVICE_CODE_RE, output),
        }

    async def start_run(
        self,
        user: UserContext,
        prompt: str,
        mode: str,
        model: str | None,
        session_id: str | None,
        assessment: RiskAssessment,
        *,
        create_new_session: bool = False,
        approved: bool,
        yolo: bool,
        secret_access_approved: bool,
    ) -> str:
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI is not installed in this image.")
        home = self.ensure_user_home(user)

        resolved_session_id = self._resolve_session(
            user=user,
            session_id=session_id,
            force_new=create_new_session,
            prompt=prompt,
        )
        session_history = self.db.list_session_context(
            resolved_session_id,
            user.user_id,
            limit=self.SESSION_CONTEXT_LIMIT,
        )

        run_id = str(uuid.uuid4())
        self.db.create_run(
            {
                "id": run_id,
                "user_id": user.user_id,
                "session_id": resolved_session_id,
                "prompt": prompt,
                "mode": mode,
                "status": "queued",
                "risk_level": assessment.level,
                "approval_required": int(assessment.approval_required),
                "approved": int(approved),
                "yolo": int(yolo),
                "secret_access_approved": int(secret_access_approved),
                "started_at": utcnow(),
            }
        )
        self.db.update_session(
            resolved_session_id,
            user.user_id,
            title=self._session_title(prompt, session_history),
        )

        backup_slug = None
        backup_job_id = None
        if (
            mode == "apply"
            and assessment.configuration_change
            and self.settings.create_backup_before_first_change
        ):
            try:
                backup = await self._ensure_first_backup(run_id)
                backup_slug = backup.get("slug")
                backup_job_id = backup.get("job_id")
                self.db.update_run(run_id, backup_slug=backup_slug, backup_job_id=backup_job_id)
            except Exception as exc:
                message = f"Unable to create required pre-configuration-change backup: {exc}"
                self.db.add_event(run_id, "backup.failed", {"error": message})
                self.db.update_run(
                    run_id,
                    status="failed",
                    completed_at=utcnow(),
                    error=message,
                )
                raise RuntimeError(message) from exc

        ha_context = await self.ha.context()
        ha_context["local"] = self._local_context()
        thread = threading.Thread(
            target=self._run_codex_process,
            args=(
                run_id,
                user,
                home,
                prompt,
                mode,
                model,
                resolved_session_id,
                session_history,
                assessment,
                ha_context,
                yolo,
                secret_access_approved,
            ),
            name=f"codex-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return run_id

    async def _ensure_first_backup(self, run_id: str) -> dict[str, Any]:
        existing = self.db.get_state(FIRST_CONFIG_BACKUP_STATE) or self.db.get_state(
            LEGACY_FIRST_BACKUP_STATE
        )
        if existing:
            self.db.add_event(run_id, "backup.reused", existing)
            return existing

        name = (
            "Codex Agent pre-configuration-change "
            f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self.db.add_event(run_id, "backup.started", {"name": name})
        backup = await self.ha.create_full_backup(name)
        self.db.set_state(FIRST_CONFIG_BACKUP_STATE, backup)
        self.db.add_event(run_id, "backup.completed", backup)
        return backup

    def _run_codex_process(
        self,
        run_id: str,
        user: UserContext,
        home: Path,
        prompt: str,
        mode: str,
        model: str | None,
        session_id: str,
        session_history: list[dict[str, Any]],
        assessment: RiskAssessment,
        ha_context: dict[str, Any],
        yolo: bool,
        secret_access_approved: bool,
    ) -> None:
        self.db.update_run(run_id, status="running")
        before = None
        if mode == "apply":
            before = collect_snapshot(max_file_kb=self.settings.max_snapshot_file_kb)

        workspace = self._workspace_root()
        command = self._build_command(mode=mode, model=model, yolo=yolo, workspace=workspace)
        full_prompt = self._build_prompt(
            user=user,
            prompt=prompt,
            mode=mode,
            session_id=session_id,
            session_history=session_history,
            assessment=assessment,
            ha_context=ha_context,
            secret_access_approved=secret_access_approved,
        )
        command.append(full_prompt)
        self.db.add_event(run_id, "codex.command", {"argv": self._redacted_command(command)})

        final_message = ""
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._env(home),
            )
            assert proc.stdout is not None
            assert proc.stderr is not None

            stderr_thread = threading.Thread(
                target=self._read_stderr,
                args=(run_id, proc.stderr),
                daemon=True,
            )
            stderr_thread.start()

            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self.db.add_event(run_id, event.get("type", "codex.event"), event)
                    message = self._extract_agent_message(event)
                    if message:
                        final_message = message
                except json.JSONDecodeError:
                    self.db.add_event(run_id, "codex.stdout", line)

            exit_code = proc.wait()
            stderr_thread.join(timeout=2)
            diff = ""
            if mode == "apply" and before is not None:
                after = collect_snapshot(max_file_kb=self.settings.max_snapshot_file_kb)
                diff = diff_snapshots(before, after)
            self.db.update_run(
                run_id,
                status="completed" if exit_code == 0 else "failed",
                completed_at=utcnow(),
                exit_code=exit_code,
                final_message=final_message,
                diff=diff,
            )
        except Exception as exc:
            self.db.add_event(run_id, "codex.error", {"error": str(exc)})
            self.db.update_run(
                run_id,
                status="failed",
                completed_at=utcnow(),
                error=str(exc),
            )

    def _read_stderr(self, run_id: str, stream: Any) -> None:
        for line in stream:
            line = clean_terminal_text(line.rstrip("\n"))
            if line:
                self.db.add_event(run_id, "codex.stderr", line)

    def _build_command(
        self,
        *,
        mode: str,
        model: str | None = None,
        yolo: bool,
        workspace: Path | None = None,
    ) -> list[str]:
        command = ["codex", "exec", "--json", "--skip-git-repo-check"]
        selected_model = model or self.settings.codex_model
        if selected_model:
            command.extend(["--model", selected_model])
        if self.settings.enable_live_search:
            command.extend(["--config", 'web_search="live"'])
        command.extend(["--config", 'shell_environment_policy.inherit="all"'])
        command.extend(["--cd", str(workspace or self._workspace_root())])
        for path in MAPPED_PATHS:
            if path.exists() and path != (workspace or self._workspace_root()):
                command.extend(["--add-dir", str(path)])

        if yolo:
            command.append("--dangerously-bypass-approvals-and-sandbox")
            return command

        command.extend(["--sandbox", "danger-full-access"])
        return command

    def _build_prompt(
        self,
        *,
        user: UserContext,
        prompt: str,
        mode: str,
        session_id: str,
        session_history: list[dict[str, Any]],
        assessment: RiskAssessment,
        ha_context: dict[str, Any],
        secret_access_approved: bool,
    ) -> str:
        mode_instruction = {
            "ask": "Answer only. Do not modify files or call side-effect APIs.",
            "propose": "Propose an exact plan or patch. Do not modify files.",
            "apply": "Apply the requested change with minimal scope, then summarize what changed.",
        }[mode]

        session_context = self._render_session_context(session_history)
        return f"""
You are Codex running inside the Home Assistant Codex Agent add-on.

Home Assistant user:
- id: {user.user_id}
- username: {user.username}
- display name: {user.display_name}

Mode: {mode}
Instruction for this mode: {mode_instruction}

Risk assessment:
- level: {assessment.level}
- reasons: {", ".join(assessment.reasons)}
- secret access approved: {secret_access_approved}

Home Assistant context JSON:
{json.dumps(ha_context, indent=2, sort_keys=True)}

Mapped paths:
- /homeassistant: Home Assistant /config
- /config: this add-on's shared configuration folder
- /addon_configs: all add-on configuration folders
- /addons: local add-on folders
- /share, /media, /ssl: mapped Home Assistant folders

Operational rules:
- Do not read or modify secrets, private keys, auth caches, tokens, or credentials unless
  secret access approved is true and the user's request specifically requires it.
- Prefer Home Assistant Core API through http://supervisor/core/api and Supervisor API
  through http://supervisor when APIs are safer than direct file edits. Use the
  SUPERVISOR_TOKEN environment variable as the bearer token.
- Keep changes focused on the user's request.
- For dashboards and visual changes, prefer supported Home Assistant dashboard
  configuration patterns and preserve existing user content.
- Do not delete, purge, restore, disable authentication, expose Supervisor, or perform
  destructive operations unless the request explicitly says to do so and this run was approved.
- If a requested action is unsafe or ambiguous, stop and explain the concern.
- Before saying Home Assistant data is unavailable, inspect the mapped files and
  call the Home Assistant API when the Supervisor token is available.
- For dashboard questions, inspect /homeassistant/.storage/lovelace,
  /homeassistant/.storage/lovelace_dashboards, ui-lovelace.yaml, and any included
  dashboard YAML. Count entities from the actual dashboard configuration, not
  only from the global entity registry.
- If SUPERVISOR_TOKEN is missing, do not send an Authorization header with an
  empty bearer token.

Current session: {session_id}

Recent session context:
{session_context}

Unless explicitly asked otherwise, continue from the thread above.
- Codex's internal Linux sandbox is disabled in this add-on because Home
  Assistant OS add-on containers do not allow the bubblewrap namespace setup it
  needs. Treat the selected mode as mandatory: ask/propose must not modify
  files or call side-effect APIs; apply may change only what the user requested.

User request:
{prompt}
""".strip()

    def _resolve_session(
        self,
        user: UserContext,
        *,
        session_id: str | None,
        force_new: bool,
        prompt: str,
    ) -> str:
        if force_new:
            return self.db.create_session(user.user_id, self._session_title(prompt))

        if session_id:
            existing = self.db.get_session(session_id, user.user_id)
            if existing:
                return session_id

        latest = self.db.latest_session_id(user.user_id)
        if latest:
            return latest

        return self.db.create_session(user.user_id, self._session_title(prompt))

    def _session_title(
        self,
        prompt: str,
        session_history: list[dict[str, Any]] | None = None,
    ) -> str:
        prompts = [self._clean_for_prompt(item.get("prompt", "")) for item in session_history or []]
        prompts = [item for item in reversed(prompts) if item]
        prompts.append(self._clean_for_prompt(prompt))
        tokens: dict[str, dict[str, Any]] = {}

        for index, raw_token in enumerate(TITLE_TOKEN_RE.findall(" ".join(prompts).lower())):
            token = self._title_token(raw_token)
            if not token or token in TITLE_STOP_WORDS:
                continue
            entry = tokens.setdefault(token, {"count": 0, "first": index})
            entry["count"] += 1

        if tokens:
            ranked = sorted(
                tokens.items(),
                key=lambda item: (
                    -(item[1]["count"] * 4 + (3 if item[0] in TITLE_DOMAIN_WORDS else 0)),
                    item[1]["first"],
                ),
            )[:6]
            ordered = sorted(ranked, key=lambda item: item[1]["first"])
            title = " ".join(self._title_word(token) for token, _meta in ordered)
        else:
            title = self._clean_for_prompt(prompt)

        if len(title) > self.SESSION_TITLE_MAX:
            title = f"{title[: self.SESSION_TITLE_MAX - 1].rstrip()}…"
        return title or "Session"

    @staticmethod
    def _title_token(value: str) -> str:
        token = TITLE_TOKEN_ALIASES.get(value, value)
        if len(token) < 3 or token.isdigit() or re.fullmatch(r"\d+(st|nd|rd|th)", token):
            return ""
        return token

    @staticmethod
    def _title_word(value: str) -> str:
        known = {
            "ha": "HA",
            "yaml": "YAML",
        }
        return known.get(value, value.capitalize())

    def _render_session_context(self, session_history: list[dict[str, Any]]) -> str:
        if not session_history:
            return "No prior context in this session."

        lines: list[str] = []
        for item in reversed(session_history):
            user_request = self._clean_for_prompt(item.get("prompt", ""))
            assistant_reply = self._clean_for_prompt(item.get("final_message", ""))
            if not assistant_reply:
                assistant_reply = "[No completed response yet]"
            lines.append(f"User: {self._truncate_for_prompt(user_request, 360)}")
            lines.append(f"Assistant: {self._truncate_for_prompt(assistant_reply, 520)}")
            lines.append("")
        return self._truncate_for_prompt("\n".join(lines).strip(), self.SESSION_CONTEXT_MAX_CHARS)

    def _clean_for_prompt(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.split())

    def _truncate_for_prompt(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        truncated = value[: max_length - 1].rstrip()
        return f"{truncated}…"

    def _env(self, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        env["HOME"] = str(home)
        env.setdefault("NO_COLOR", "1")
        env["CODEX_AGENT_HOME_ASSISTANT_ROOT"] = str(WORKSPACE)
        token = supervisor_token()
        if token:
            env["SUPERVISOR_TOKEN"] = token
        else:
            env.pop("SUPERVISOR_TOKEN", None)
        return env

    def _workspace_root(self) -> Path:
        return WORKSPACE if WORKSPACE.exists() else Path("/")

    def _local_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            "paths": {},
            "dashboard_files": [],
        }
        for path in MAPPED_PATHS:
            context["paths"][str(path)] = {
                "exists": path.exists(),
                "is_dir": path.is_dir(),
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
            }

        dashboard_candidates = list(LOCAL_CONTEXT_FILES)
        dashboards_dir = WORKSPACE / "dashboards"
        if dashboards_dir.exists():
            dashboard_candidates.extend(sorted(dashboards_dir.glob("**/*.yaml"))[:12])

        max_bytes = max(16, self.settings.max_snapshot_file_kb) * 1024
        for path in dashboard_candidates:
            item: dict[str, Any] = {"path": str(path), "exists": path.exists()}
            if path.exists() and path.is_file():
                try:
                    raw = path.read_bytes()
                    item["bytes"] = len(raw)
                    if len(raw) <= max_bytes and b"\x00" not in raw:
                        item["content"] = raw.decode("utf-8", errors="replace")
                    else:
                        item["omitted"] = "file is binary or larger than the context limit"
                except OSError as exc:
                    item["error"] = str(exc)
            context["dashboard_files"].append(item)
        return context

    @staticmethod
    def _validate_auth_json(parsed: Any) -> None:
        if not isinstance(parsed, dict):
            raise ValueError("auth.json must be a JSON object.")

        auth_mode = parsed.get("auth_mode")
        if not isinstance(auth_mode, str) or not auth_mode:
            raise ValueError("auth.json must include a non-empty auth_mode field.")

        api_key = parsed.get("OPENAI_API_KEY")
        if isinstance(api_key, str) and api_key:
            return

        if auth_mode != "chatgpt":
            raise ValueError("auth.json must contain ChatGPT tokens or a non-empty OPENAI_API_KEY.")

        last_refresh = parsed.get("last_refresh")
        if not isinstance(last_refresh, str):
            raise ValueError("auth.json must include a last_refresh timestamp.")
        try:
            parsed_refresh = datetime.fromisoformat(last_refresh.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("auth.json last_refresh must be an RFC3339 timestamp.") from exc
        if "T" not in last_refresh or parsed_refresh.tzinfo is None:
            raise ValueError("auth.json last_refresh must be an RFC3339 timestamp.")

        tokens = parsed.get("tokens")
        if not isinstance(tokens, dict):
            raise ValueError("auth.json must include a tokens object.")

        required_tokens = ("access_token", "account_id", "id_token", "refresh_token")
        missing = [
            name
            for name in required_tokens
            if not isinstance(tokens.get(name), str) or not tokens.get(name)
        ]
        if missing:
            fields = ", ".join(missing)
            raise ValueError(f"auth.json tokens must include non-empty fields: {fields}.")

    @staticmethod
    def _redacted_command(command: list[str]) -> list[str]:
        if not command:
            return command
        redacted = command[:-1] + ["<prompt>"]
        return redacted

    @staticmethod
    def _first_match(pattern: re.Pattern[str], value: str) -> str:
        match = pattern.search(value)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_agent_message(event: dict[str, Any]) -> str:
        if event.get("type") not in {"item.completed", "message.completed"}:
            return ""
        item = event.get("item") if isinstance(event.get("item"), dict) else event
        item_type = item.get("type")
        if item_type == "agent_message" and isinstance(item.get("text"), str):
            return item["text"]
        if item_type == "message" and item.get("role") in {None, "assistant"}:
            return extract_text_from_content(item.get("content"))
        return ""


def clean_terminal_text(value: str) -> str:
    without_ansi = ANSI_ESCAPE_RE.sub("", value)
    without_controls = CONTROL_CHAR_RE.sub("", without_ansi)
    return without_controls.replace("\r", "")


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(part for part in parts if part)
