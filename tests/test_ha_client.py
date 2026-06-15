import asyncio

from codex_agent.ha_client import HomeAssistantClient


def test_headers_omit_empty_authorization() -> None:
    client = HomeAssistantClient(token="")

    assert client.headers == {"Content-Type": "application/json"}
    assert client.token_available is False


def test_headers_include_non_empty_authorization() -> None:
    client = HomeAssistantClient(token="abc123")

    assert client.headers["Authorization"] == "Bearer abc123"
    assert client.token_available is True


def test_context_reports_missing_supervisor_token() -> None:
    client = HomeAssistantClient(token="")

    context = asyncio.run(client.context())

    assert context["supervisor_token_available"] is False
    assert context["core"]["error"] == "SUPERVISOR_TOKEN is not available in this environment."


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
