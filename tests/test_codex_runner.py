from codex_agent import codex_runner
from codex_agent.codex_runner import MANAGED_CODEX_CONFIG, CodexRunner
from codex_agent.security import UserContext
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


def test_ask_command_uses_supported_exec_flags() -> None:
    command = make_runner()._build_command(mode="ask", yolo=False)

    assert command[:3] == ["codex", "exec", "--json"]
    assert "--search" not in command
    assert "--ask-for-approval" not in command
    assert command[-2:] == ["--sandbox", "read-only"]
    assert command[command.index("--config") + 1] == 'web_search="live"'


def test_apply_command_uses_workspace_write() -> None:
    command = make_runner()._build_command(mode="apply", yolo=False)

    assert command[-2:] == ["--sandbox", "workspace-write"]


def test_yolo_command_bypasses_sandbox() -> None:
    command = make_runner()._build_command(mode="apply", yolo=True)

    assert "--dangerously-bypass-approvals-and-sandbox" in command
    assert "--sandbox" not in command


def test_live_search_can_be_left_as_default() -> None:
    command = make_runner(Settings(enable_live_search=False))._build_command(
        mode="ask",
        yolo=False,
    )

    assert "--config" not in command


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
