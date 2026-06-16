from __future__ import annotations

import json

from codex_agent.event_view import display_events


def _event(event_id: int, event_type: str, payload: dict | str) -> dict:
    return {
        "id": event_id,
        "created_at": "2026-06-16T10:00:00Z",
        "type": event_type,
        "payload": payload,
    }


def test_tool_execution_event_is_human_summary() -> None:
    payload = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "curl -H 'Authorization: Bearer abcdef' http://supervisor/core/api/services/light/turn_on",
            "aggregated_output": "{\"result\": \"ok\", \"lights\": 4}",
            "exit_code": 0,
        },
    }

    event = _event(1, "item.completed", json.dumps(payload))
    rendered = display_events([event])[0]

    assert rendered["type"] == "Tool finished"
    assert "Tool finished" in rendered["payload"]
    assert "json" not in rendered["payload"].lower()
    assert "{\"result\"" not in rendered["display"]["details"]
    assert "Structured output omitted" in rendered["display"]["details"]
    assert "[redacted]" in rendered["payload"]


def test_agent_answer_shows_as_markdown_friendly_text() -> None:
    payload = {
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": "There are **3** automations in the default dashboard.",
        },
    }

    event = _event(2, "item.completed", json.dumps(payload))
    rendered = display_events([event])[0]

    assert rendered["type"] == "Answer"
    assert rendered["display"]["kind"] == "message"
    assert rendered["payload"] == "There are **3** automations in the default dashboard."
    assert "{" not in rendered["payload"]


def test_turn_completed_reports_token_summary() -> None:
    payload = {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 250,
            "output_tokens": 77,
        },
    }
    event = _event(3, "item.completed", json.dumps(payload))

    rendered = display_events([event])[0]

    assert rendered["type"] == "Done"
    assert "250" in rendered["payload"]
    assert "77" in rendered["payload"]
