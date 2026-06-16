import asyncio

from codex_agent import ha_client
from codex_agent.ha_client import HomeAssistantClient, supervisor_token


def test_headers_omit_empty_authorization() -> None:
    client = HomeAssistantClient(token="")

    assert client.headers == {"Content-Type": "application/json"}
    assert client.token_available is False


def test_headers_include_non_empty_authorization() -> None:
    client = HomeAssistantClient(token="abc123")

    assert client.headers["Authorization"] == "Bearer abc123"
    assert client.token_available is True


def test_supervisor_token_reads_s6_environment_file(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "SUPERVISOR_TOKEN"
    token_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(ha_client, "SUPERVISOR_TOKEN_FILES", (token_file,))

    assert supervisor_token() == "from-file"
    assert HomeAssistantClient().headers["Authorization"] == "Bearer from-file"


def test_supervisor_token_prefers_environment(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "SUPERVISOR_TOKEN"
    token_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "from-env")
    monkeypatch.setattr(ha_client, "SUPERVISOR_TOKEN_FILES", (token_file,))

    assert supervisor_token() == "from-env"


def test_context_reports_missing_supervisor_token() -> None:
    client = HomeAssistantClient(token="")

    context = asyncio.run(client.context())

    assert context["supervisor_token_available"] is False
    assert context["core"]["error"] == "SUPERVISOR_TOKEN is not available in this environment."


def test_create_full_backup_uses_documented_payload() -> None:
    client = HomeAssistantClient(token="token")
    captured = {}

    async def fake_post_json(path: str, payload: dict) -> dict:
        captured["path"] = path
        captured["payload"] = payload
        return {"slug": "backup-1"}

    client.post_json = fake_post_json  # type: ignore[method-assign]

    result = asyncio.run(client.create_full_backup("Test backup"))

    assert result == {"slug": "backup-1"}
    assert captured == {
        "path": "/backups/new/full",
        "payload": {
            "name": "Test backup",
            "compressed": True,
            "background": False,
        },
    }


def test_summarize_states_counts_domains() -> None:
    summary = HomeAssistantClient._summarize_states(
        [
            {"entity_id": "light.kitchen"},
            {"entity_id": "light.hall"},
            {"entity_id": "sensor.temperature"},
        ]
    )

    assert summary["count"] == 3
    assert summary["domain_counts"] == {"light": 2, "sensor": 1}
    assert summary["sample_entities"]["light"] == ["light.kitchen", "light.hall"]
