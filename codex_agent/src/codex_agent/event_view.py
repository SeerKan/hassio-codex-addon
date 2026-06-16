from __future__ import annotations

import json
import re
from typing import Any

ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
HEADER_RE = re.compile(r"Authorization:\s*Bearer\s+[^\s\"']+", re.IGNORECASE)
BEARER_RE = re.compile(r"\bBearer\s+(?!\[redacted\])[^\s\"']+", re.IGNORECASE)


def display_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [display_event(event) for event in raw_events]


def display_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = _parse_payload(event.get("payload"))
    event_type = event.get("type") or "event"

    if event_type == "codex.command":
        return _compose(event, "Run started", _command_summary(payload), kind="activity")

    if event_type in {"codex.stderr", "codex.error"}:
        message = _human_message(payload)
        if "Reading additional input" in message:
            message = "Codex received the request"
            return _compose(event, "Prompt sent", message, kind="activity")
        return _compose(event, "Notice", _short_text(message), kind="notice")

    if event_type.startswith("backup."):
        return _backup_event(event_type, payload, event)

    if isinstance(payload, str):
        return _compose(
            event,
            _label(event_type),
            _short_text(payload),
            kind="activity",
        )

    if not isinstance(payload, dict):
        return _compose(event, _label(event_type), str(payload), kind="activity")

    inner_type = payload.get("type", event_type)

    if inner_type in {"thread.started"}:
        thread_id = _clean_text(payload.get("thread_id", ""))
        return _compose(event, "Session opened", f"Thread {thread_id}" if thread_id else "Session opened")

    if inner_type in {"turn.started"}:
        return _compose(event, "Working", "Thinking through the request")

    if inner_type in {"turn.completed"}:
        usage = payload.get("usage")
        if isinstance(usage, dict):
            summary = _usage_summary(usage)
        else:
            summary = "Completed"
        return _compose(event, "Done", summary)

    if inner_type in {"turn.failed", "error"}:
        message = _human_message(payload)
        return _compose(event, "Run failed", message, kind="message")

    if inner_type in {"item.started", "item.completed"}:
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        return _item_event(event, inner_type, item)

    return _compose(event, _label(inner_type), _human_message(payload))


def _command_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "Preparing command"
    argv = payload.get("argv")
    if not isinstance(argv, list):
        return "Preparing command"
    parts = [str(item) for item in argv if item != "<prompt>"]
    return "Running Codex command: " + _short_text(" ".join(parts[:8]), max_length=220)


def _backup_event(event_type: str, payload: Any, event: dict[str, Any]) -> dict[str, Any]:
    payload_dict = payload if isinstance(payload, dict) else {}
    if event_type == "backup.started":
        name = _clean_text(payload_dict.get("name", "pre-change backup"))
        return _compose(event, "Backup", f"Creating {name}", kind="activity")
    if event_type == "backup.completed":
        name = _clean_text(payload_dict.get("slug", payload_dict.get("name", "backup")))
        return _compose(event, "Backup", f"Created {name}")
    if event_type == "backup.reused":
        name = _clean_text(payload_dict.get("slug", payload_dict.get("name", "backup")))
        return _compose(event, "Backup", f"Using existing {name}", kind="activity")
    return _compose(event, "Backup", _human_message(payload_dict), kind="activity")


def _item_event(event: dict[str, Any], event_type: str, item: dict[str, Any]) -> dict[str, Any]:
    item_type = _clean_text(item.get("type") or "item")
    complete = event_type == "item.completed"

    if item_type == "agent_message" or (item_type == "message" and item.get("role") in {"", None, "assistant"}):
        message = _extract_item_text(item)
        if not message:
            message = "(empty response)"
        return _compose(
            event,
            "Answer",
            message,
            kind="message",
            markdown=True,
        )

    if item_type == "reasoning":
        text = _extract_item_text(item)
        if not text:
            text = "Reasoning finished" if complete else "Reasoning"
        return _compose(event, "Thinking", text, kind="activity")

    if item_type in {
        "command_execution",
        "exec_command",
        "function_call",
        "local_shell_call",
        "mcp_tool_call",
        "shell_command",
        "tool_call",
        "web_search_call",
    }:
        summary = _tool_summary(item, complete)
        details = _tool_details(item)
        return _compose(event, "Tool finished" if complete else "Tool started", summary, kind="tool", details=details)

    return _compose(event, _label(item_type), _extract_item_text(item) or _human_message(item), kind="activity")


def _compose(
    event: dict[str, Any],
    title: str,
    summary: Any,
    *,
    kind: str = "activity",
    details: str = "",
    markdown: bool = False,
) -> dict[str, Any]:
    payload = _short_text(summary if summary is not None else "", max_length=3000)
    return {
        "id": event.get("id"),
        "created_at": event.get("created_at"),
        "type": title,
        "payload": payload,
        "display": {
            "title": title,
            "summary": payload,
            "details": _clean_text(details),
            "kind": kind,
            "markdown": bool(markdown),
        },
    }


def _tool_summary(item: dict[str, Any], complete: bool) -> str:
    command = _clean_text(item.get("command", ""))
    if command:
        if "http://supervisor" in command or "/core/api" in command or "/backups" in command:
            base = "Home Assistant API request"
        elif "curl" in command:
            base = "Home Assistant HTTP request"
        else:
            base = "Shell command"
        status = "completed" if complete else "started"
        if "exit_code" in item and item.get("exit_code") not in {None, ""}:
            status = f"completed (exit code {item.get('exit_code')})"
        return f"{base} {status}: { _short_text(_redact_sensitive(command), max_length=200)}"

    if item.get("name"):
        return f"Tool {item.get('name')}"
    if item.get("tool"):
        return f"Tool {item.get('tool')}"
    return "Tool completed" if complete else "Tool started"


def _tool_details(item: dict[str, Any]) -> str:
    parts: list[str] = []

    if item.get("command"):
        parts.append(f"Command\n{_redact_sensitive(_clean_text(item.get('command')))}")

    output = item.get("aggregated_output")
    if output is None:
        output = item.get("output")
    if output is None:
        output = item.get("result")

    output_text = _clean_text(output)
    if output_text:
        if _looks_like_json(output_text):
            parts.append("Output\nStructured output omitted")
        else:
            parts.append(f"Output\n{output_text}")

    if item.get("status"):
        parts.append(f"Status\n{item.get('status')}")

    if item.get("exit_code") is not None:
        parts.append(f"Exit code\n{item.get('exit_code')}")

    return "\n\n".join(parts)


def _parse_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        candidate = _clean_text(payload)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return candidate
    return payload


def _human_message(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if not isinstance(value, dict):
        return str(value or "")
    if value.get("message"):
        return _clean_text(value.get("message"))
    if value.get("error"):
        return _clean_text(value.get("error"))
    return _summarize_object(value)


def _extract_item_text(item: dict[str, Any]) -> str:
    for key in ("text", "output", "result", "summary"):
        if isinstance(item.get(key), str):
            value = _clean_text(item.get(key))
            if value:
                return value

    aggregated = item.get("aggregated_output")
    if isinstance(aggregated, str) and aggregated:
        return _clean_text(aggregated)

    content = item.get("content")
    if isinstance(content, str):
        return _clean_text(content)
    if isinstance(content, list):
        chunks: list[str] = []
        for entry in content:
            if isinstance(entry, str):
                chunks.append(entry)
            elif isinstance(entry, dict):
                text = entry.get("text") or entry.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


def _label(type_value: str) -> str:
    return str(type_value).replace("_", " ").replace(".", " ").title()


def _usage_summary(usage: dict[str, Any]) -> str:
    input_tokens = usage.get("input_tokens") or usage.get("total_input_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("total_output_tokens")
    if not input_tokens and not output_tokens:
        return "Completed"
    input_text = _format_count(input_tokens)
    output_text = _format_count(output_tokens)
    if input_tokens and output_tokens:
        return f"Used {input_text} input · {output_text} output tokens"
    if input_tokens:
        return f"Used {input_text} input tokens"
    return f"Used {output_text} output tokens"


def _format_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _summarize_object(value: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    pieces = []
    for key, item in list(value.items())[:6]:
        if isinstance(item, (dict, list)):
            pieces.append(f"{key}: [{type(item).__name__}]")
        else:
            text = _short_text(_clean_text(item), 120)
            if text:
                pieces.append(f"{key}: {text}")
    return "; ".join(pieces)


def _short_text(value: Any, max_length: int = 500) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}…"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = ANSI_ESCAPE_RE.sub("", text)
    text = CONTROL_CHAR_RE.sub("", text)
    text = text.replace("\r", "")
    return _redact_sensitive(text)


def _looks_like_json(value: str) -> bool:
    if not value:
        return False
    text = value.strip()
    if not text:
        return False
    if not ((text[0] == "{" and text[-1] == "}") or (text[0] == "[" and text[-1] == "]")):
        return False
    try:
        json.loads(text)
        return True
    except (TypeError, json.JSONDecodeError):
        pass

    unescaped = text.replace('\\"', '"')
    try:
        json.loads(unescaped)
    except (TypeError, json.JSONDecodeError):
        return False
    return True


def _redact_sensitive(value: str) -> str:
    value = HEADER_RE.sub("Authorization: Bearer [redacted]", value)
    value = BEARER_RE.sub("Bearer [redacted]", value)
    return value.replace("$SUPERVISOR_TOKEN", "[SUPERVISOR_TOKEN]")
