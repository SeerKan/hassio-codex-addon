from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .database import Database, utcnow
from .ha_client import HomeAssistantClient
from .security import RiskAssessment, UserContext
from .settings import DATA_DIR, Settings
from .snapshot import collect_snapshot, diff_snapshots

USERS_DIR = DATA_DIR / "users"
WORKSPACE = Path("/homeassistant")


class CodexRunner:
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
        if not config.exists():
            config.write_text(
                'cli_auth_credentials_store = "file"\n'
                'approval_policy = "on-request"\n'
                'sandbox_mode = "workspace-write"\n',
                encoding="utf-8",
            )
            config.chmod(0o600)
        return home

    def auth_status(self, user: UserContext) -> dict[str, Any]:
        home = self.ensure_user_home(user)
        auth_file = home / "auth.json"
        status = {"configured": auth_file.exists(), "auth_file": str(auth_file)}
        if auth_file.exists():
            try:
                raw = json.loads(auth_file.read_text(encoding="utf-8"))
                status["auth_mode"] = raw.get("auth_mode", "unknown")
                status["last_refresh"] = raw.get("last_refresh")
            except json.JSONDecodeError:
                status["configured"] = False
                status["error"] = "auth.json is not valid JSON"
        return status

    def import_auth_json(self, user: UserContext, content: str) -> dict[str, Any]:
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or "auth_mode" not in parsed:
            raise ValueError("auth.json must be a JSON object with an auth_mode field.")
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
                self.db.append_auth_output(job_id, line)
            exit_code = proc.wait()
            self.db.finish_auth_job(job_id, "completed" if exit_code == 0 else "failed", exit_code)
        except Exception as exc:
            self.db.append_auth_output(job_id, f"\nLogin process failed: {exc}\n")
            self.db.finish_auth_job(job_id, "failed", None)

    async def start_run(
        self,
        user: UserContext,
        prompt: str,
        mode: str,
        assessment: RiskAssessment,
        *,
        approved: bool,
        yolo: bool,
        secret_access_approved: bool,
    ) -> str:
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI is not installed in this image.")
        home = self.ensure_user_home(user)
        run_id = str(uuid.uuid4())
        self.db.create_run(
            {
                "id": run_id,
                "user_id": user.user_id,
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

        backup_slug = None
        backup_job_id = None
        if mode == "apply" and self.settings.create_backup_before_first_change:
            backup = await self._ensure_first_backup(run_id)
            backup_slug = backup.get("slug")
            backup_job_id = backup.get("job_id")
            self.db.update_run(run_id, backup_slug=backup_slug, backup_job_id=backup_job_id)

        ha_context = await self.ha.context()
        thread = threading.Thread(
            target=self._run_codex_process,
            args=(
                run_id,
                user,
                home,
                prompt,
                mode,
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
        existing = self.db.get_state("first_change_backup")
        if existing:
            self.db.add_event(run_id, "backup.reused", existing)
            return existing

        name = f"Codex Agent pre-change {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        self.db.add_event(run_id, "backup.started", {"name": name})
        backup = await self.ha.create_full_backup(name)
        self.db.set_state("first_change_backup", backup)
        self.db.add_event(run_id, "backup.completed", backup)
        return backup

    def _run_codex_process(
        self,
        run_id: str,
        user: UserContext,
        home: Path,
        prompt: str,
        mode: str,
        assessment: RiskAssessment,
        ha_context: dict[str, Any],
        yolo: bool,
        secret_access_approved: bool,
    ) -> None:
        self.db.update_run(run_id, status="running")
        before = None
        if mode == "apply":
            before = collect_snapshot(max_file_kb=self.settings.max_snapshot_file_kb)

        command = self._build_command(mode=mode, yolo=yolo)
        full_prompt = self._build_prompt(
            user=user,
            prompt=prompt,
            mode=mode,
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
                cwd=str(WORKSPACE if WORKSPACE.exists() else Path("/")),
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
                    if event.get("type") == "item.completed":
                        item = event.get("item") or {}
                        if item.get("type") == "agent_message":
                            final_message = item.get("text") or final_message
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
            line = line.rstrip("\n")
            if line:
                self.db.add_event(run_id, "codex.stderr", line)

    def _build_command(self, *, mode: str, yolo: bool) -> list[str]:
        command = ["codex", "exec", "--json", "--skip-git-repo-check"]
        if self.settings.codex_model:
            command.extend(["--model", self.settings.codex_model])
        if self.settings.enable_live_search:
            command.append("--search")

        if yolo:
            command.append("--dangerously-bypass-approvals-and-sandbox")
            return command

        if mode in {"ask", "propose"}:
            command.extend(["--sandbox", "read-only", "--ask-for-approval", "never"])
        else:
            command.extend(["--sandbox", "workspace-write", "--ask-for-approval", "never"])
        return command

    def _build_prompt(
        self,
        *,
        user: UserContext,
        prompt: str,
        mode: str,
        assessment: RiskAssessment,
        ha_context: dict[str, Any],
        secret_access_approved: bool,
    ) -> str:
        mode_instruction = {
            "ask": "Answer only. Do not modify files or call side-effect APIs.",
            "propose": "Propose an exact plan or patch. Do not modify files.",
            "apply": "Apply the requested change with minimal scope, then summarize what changed.",
        }[mode]
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

User request:
{prompt}
""".strip()

    def _env(self, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        env["HOME"] = str(home)
        env.setdefault("NO_COLOR", "1")
        return env

    @staticmethod
    def _redacted_command(command: list[str]) -> list[str]:
        if not command:
            return command
        redacted = command[:-1] + ["<prompt>"]
        return redacted
