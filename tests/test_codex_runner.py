import asyncio
from pathlib import Path

from codex_agent import codex_runner
from codex_agent.codex_runner import MANAGED_CODEX_CONFIG, CodexRunner, clean_terminal_text
from codex_agent.database import Database
from codex_agent.security import RiskAssessment, UserContext
from codex_agent.settings import Settings

CHATGPT_AUTH_JSON = """
{
  "OPENAI_API_KEY": null,
  "auth_mode": "chatgpt",
  "last_refresh": "2026-06-15T21:32:31.000Z",
  "tokens": {
    "access_token": "fake-access",
    "account_id": "fake-account",
    "id_token": "fake-id",
    "refresh_token": "fake-refresh"
  }
}
"""


def make_runner(settings: Settings | None = None) -> CodexRunner:
    runner = object.__new__(CodexRunner)
    runner.settings = settings or Settings()
    return runner


class FakeHomeAssistant:
    async def context(self) -> dict:
        return {"core": {"version": "test"}}


def make_startable_runner(tmp_path, monkeypatch) -> tuple[CodexRunner, Database]:
    monkeypatch.setattr(codex_runner, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(codex_runner.shutil, "which", lambda _name: "/usr/bin/codex")
    db = Database(tmp_path / "codex_agent.sqlite3")
    runner = CodexRunner(db, Settings(create_backup_before_first_change=True))
    runner.ha = FakeHomeAssistant()
    monkeypatch.setattr(runner, "_run_codex_process", lambda *_args: None)
    return runner, db


def test_ask_command_uses_supported_exec_flags() -> None:
    command = make_runner()._build_command(mode="ask", yolo=False, workspace=Path("/homeassistant"))

    assert command[:3] == ["codex", "exec", "--json"]
    assert "--search" not in command
    assert "--ask-for-approval" not in command
    assert command[-2:] == ["--sandbox", "danger-full-access"]
    assert command[command.index("--config") + 1] == 'web_search="live"'
    assert 'shell_environment_policy.inherit="all"' in command
    assert command[command.index("--cd") + 1] == "/homeassistant"


def test_apply_command_uses_unsandboxed_addon_execution() -> None:
    command = make_runner()._build_command(
        mode="apply",
        yolo=False,
        workspace=Path("/homeassistant"),
    )

    assert command[-2:] == ["--sandbox", "danger-full-access"]
    assert "workspace-write" not in command
    assert "read-only" not in command


def test_yolo_command_bypasses_sandbox() -> None:
    command = make_runner()._build_command(
        mode="apply",
        yolo=True,
        workspace=Path("/homeassistant"),
    )

    assert "--dangerously-bypass-approvals-and-sandbox" in command
    assert "--sandbox" not in command


def test_live_search_can_be_left_as_default() -> None:
    command = make_runner(Settings(enable_live_search=False))._build_command(
        mode="ask",
        yolo=False,
        workspace=Path("/homeassistant"),
    )

    assert 'web_search="live"' not in command


def test_selected_model_is_passed_to_codex_exec() -> None:
    command = make_runner()._build_command(
        mode="ask",
        model="gpt-5.4-mini",
        yolo=False,
        workspace=Path("/homeassistant"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.4-mini"


def test_session_title_summarizes_topic_instead_of_copying_prompt() -> None:
    prompt = (
        "I want to have a couple of screenes for the lights in camera oaspeti. "
        "One sceen should be all the lights on at max brightness with a neutral white."
    )

    title = make_runner()._session_title(prompt)

    assert title == "Scenes Lights Camera Oaspeti Brightness Neutral"
    assert title != prompt[: len(title)]


def test_session_title_uses_existing_thread_context() -> None:
    history = [
        {
            "prompt": "Create bright and dim scenes for the camera oaspeti lights",
            "final_message": "Created two scenes.",
        }
    ]

    title = make_runner()._session_title("Make the night scene softer", history)

    assert "Scenes" in title
    assert "Lights" in title
    assert "Camera" in title


def test_runtime_apply_does_not_create_first_backup(tmp_path, monkeypatch) -> None:
    runner, db = make_startable_runner(tmp_path, monkeypatch)
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    backup_calls = []

    async def fake_backup(run_id: str) -> dict:
        backup_calls.append(run_id)
        return {"slug": "backup-runtime"}

    monkeypatch.setattr(runner, "_ensure_first_backup", fake_backup)
    assessment = RiskAssessment(
        level="medium",
        approval_required=False,
        configuration_change=False,
    )

    run_id = asyncio.run(
        runner.start_run(
            user,
            "Turn on the kitchen lights",
            "apply",
            "gpt-5.5",
            None,
            assessment,
            create_new_session=False,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )

    assert backup_calls == []
    assert db.get_run(run_id)["backup_slug"] is None


def test_configuration_apply_creates_first_backup(tmp_path, monkeypatch) -> None:
    runner, db = make_startable_runner(tmp_path, monkeypatch)
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    backup_calls = []

    async def fake_backup(run_id: str) -> dict:
        backup_calls.append(run_id)
        return {"slug": "backup-config", "job_id": "job-1"}

    monkeypatch.setattr(runner, "_ensure_first_backup", fake_backup)
    assessment = RiskAssessment(
        level="medium",
        approval_required=False,
        configuration_change=True,
    )

    run_id = asyncio.run(
        runner.start_run(
            user,
            "Add a dashboard card for the thermostat",
            "apply",
            "gpt-5.5",
            None,
            assessment,
            create_new_session=False,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )

    assert backup_calls == [run_id]
    run = db.get_run(run_id)
    assert run["backup_slug"] == "backup-config"
    assert run["backup_job_id"] == "job-1"


def test_runs_use_existing_session_when_provided(tmp_path, monkeypatch) -> None:
    runner, db = make_startable_runner(tmp_path, monkeypatch)
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    session_id = db.create_session(user.user_id, "Kitchen")
    assessment = RiskAssessment(
        level="medium",
        approval_required=False,
        configuration_change=False,
    )

    first = asyncio.run(
        runner.start_run(
            user,
            "How many lights are on?",
            "ask",
            "gpt-5.5",
            session_id,
            assessment,
            create_new_session=False,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )
    second = asyncio.run(
        runner.start_run(
            user,
            "And how many lights are off?",
            "ask",
            "gpt-5.5",
            session_id,
            assessment,
            create_new_session=False,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )

    assert db.get_run(first)["session_id"] == session_id
    assert db.get_run(second)["session_id"] == session_id
    assert len(db.list_runs(user.user_id, session_id=session_id)) == 2


def test_list_runs_can_return_session_conversation_order(tmp_path, monkeypatch) -> None:
    _runner, db = make_startable_runner(tmp_path, monkeypatch)
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    session_id = db.create_session(user.user_id, "Kitchen")
    for index, prompt in enumerate(["First message", "Second message"], start=1):
        db.create_run(
            {
                "id": f"run-{index}",
                "user_id": user.user_id,
                "session_id": session_id,
                "prompt": prompt,
                "mode": "ask",
                "status": "completed",
                "risk_level": "low",
                "approval_required": 0,
                "approved": 0,
                "yolo": 0,
                "secret_access_approved": 0,
                "started_at": f"2026-06-19T12:0{index}:00+00:00",
            }
        )

    prompts = [
        run["prompt"]
        for run in db.list_runs(user.user_id, session_id=session_id, order="asc")
    ]

    assert prompts == ["First message", "Second message"]


def test_create_new_session_forces_new_thread(tmp_path, monkeypatch) -> None:
    runner, db = make_startable_runner(tmp_path, monkeypatch)
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    initial_session_id = db.create_session(user.user_id, "Kitchen")
    assessment = RiskAssessment(
        level="medium",
        approval_required=False,
        configuration_change=False,
    )

    first = asyncio.run(
        runner.start_run(
            user,
            "Open dashboard entities",
            "ask",
            "gpt-5.5",
            initial_session_id,
            assessment,
            create_new_session=True,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )
    second = asyncio.run(
        runner.start_run(
            user,
            "Now check automations",
            "ask",
            "gpt-5.5",
            db.get_run(first)["session_id"],
            assessment,
            create_new_session=True,
            approved=False,
            yolo=False,
            secret_access_approved=False,
        )
    )

    assert db.get_run(first)["session_id"] != initial_session_id
    assert db.get_run(second)["session_id"] != initial_session_id
    assert db.get_run(second)["session_id"] != db.get_run(first)["session_id"]
    assert len(db.list_runs(user.user_id, session_id=initial_session_id)) == 0
    assert len(db.list_runs(user.user_id, session_id=db.get_run(first)["session_id"])) == 1
    assert len(db.list_runs(user.user_id, session_id=db.get_run(second)["session_id"])) == 1


def test_ensure_user_home_repairs_old_managed_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(codex_runner, "USERS_DIR", tmp_path / "users")
    runner = make_runner()
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    home = runner.ensure_user_home(user)
    config = home / "config.toml"
    config.write_text(
        'cli_auth_credentials_store = "file"\n'
        'approval_policy = "on-request"\n'
        'sandbox_mode = "workspace-write"\n',
        encoding="utf-8",
    )

    runner.ensure_user_home(user)

    assert config.read_text(encoding="utf-8") == MANAGED_CODEX_CONFIG


def test_import_auth_accepts_chatgpt_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(codex_runner, "USERS_DIR", tmp_path / "users")
    runner = make_runner()
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")

    status = runner.import_auth_json(user, CHATGPT_AUTH_JSON)

    assert status["configured"] is True
    assert status["auth_mode"] == "chatgpt"
    assert status["last_refresh"] == "2026-06-15T21:32:31.000Z"


def test_import_auth_rejects_invalid_last_refresh(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(codex_runner, "USERS_DIR", tmp_path / "users")
    runner = make_runner()
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    auth_json = CHATGPT_AUTH_JSON.replace("2026-06-15T21:32:31.000Z", "local-test")

    try:
        runner.import_auth_json(user, auth_json)
    except ValueError as exc:
        assert "last_refresh must be an RFC3339 timestamp" in str(exc)
    else:
        raise AssertionError("Expected invalid last_refresh to be rejected.")


def test_auth_status_reports_invalid_auth_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(codex_runner, "USERS_DIR", tmp_path / "users")
    runner = make_runner()
    user = UserContext(user_id="user-1", username="zoli", display_name="Zoltan")
    home = runner.ensure_user_home(user)
    (home / "auth.json").write_text('{"auth_mode":"chatgpt"}', encoding="utf-8")

    status = runner.auth_status(user)

    assert status["configured"] is False
    assert status["error"] == "auth.json must include a last_refresh timestamp."


def test_clean_terminal_text_strips_ansi_control_codes() -> None:
    raw = "\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\r\n"

    assert clean_terminal_text(raw) == "https://auth.openai.com/codex/device\n"


def test_auth_job_view_extracts_login_url_and_code() -> None:
    runner = make_runner()
    job = {
        "id": "job-1",
        "status": "running",
        "output": (
            "Open \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n"
            "Code \x1b[94mABCD-12345\x1b[0m\n"
        ),
    }

    view = runner.auth_job_view(job)

    assert view["login_url"] == "https://auth.openai.com/codex/device"
    assert view["device_code"] == "ABCD-12345"
    assert "\x1b" not in view["output"]


def test_extract_agent_message_from_message_content() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "There are 4 lights."}],
        },
    }

    assert CodexRunner._extract_agent_message(event) == "There are 4 lights."


def test_local_context_includes_dashboard_files(tmp_path, monkeypatch) -> None:
    homeassistant = tmp_path / "homeassistant"
    storage = homeassistant / ".storage"
    storage.mkdir(parents=True)
    (storage / "lovelace").write_text('{"views":[]}', encoding="utf-8")
    monkeypatch.setattr(codex_runner, "WORKSPACE", homeassistant)
    monkeypatch.setattr(codex_runner, "MAPPED_PATHS", (homeassistant,))
    monkeypatch.setattr(codex_runner, "LOCAL_CONTEXT_FILES", (storage / "lovelace",))
    runner = make_runner()

    context = runner._local_context()

    assert context["paths"][str(homeassistant)]["exists"] is True
    assert context["dashboard_files"] == [
        {
            "path": str(storage / "lovelace"),
            "exists": True,
            "bytes": 12,
            "content": '{"views":[]}',
        }
    ]
