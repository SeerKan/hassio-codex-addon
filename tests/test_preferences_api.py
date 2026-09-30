from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codex_agent import database as database_module
from codex_agent.database import Database

HEADERS = {
    "X-Remote-User-Id": "user-1",
    "X-Remote-User-Name": "zoltan",
    "X-Remote-User-Display-Name": "Zoltan",
}


async def fake_ha_context() -> dict:
    return {"core": {"version": "test"}, "core_config": {"version": "test"}}


def make_client(tmp_path, monkeypatch) -> TestClient:
    class TestDatabase(Database):
        def __init__(self, path=None) -> None:
            super().__init__(path or tmp_path / "startup.sqlite3")

    monkeypatch.setattr(database_module, "Database", TestDatabase)
    from codex_agent import main

    monkeypatch.setattr(main, "db", TestDatabase(tmp_path / "codex_agent.sqlite3"))
    monkeypatch.setattr(main.runner, "auth_status", lambda _user: {"configured": False})
    monkeypatch.setattr(main.runner.ha, "context", fake_ha_context)
    return TestClient(main.app)


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-6-astra"])
def test_user_preferences_round_trip(tmp_path, monkeypatch, model) -> None:
    client = make_client(tmp_path, monkeypatch)

    initial = client.get("/api/status", headers=HEADERS)

    assert initial.status_code == 200
    assert initial.json()["preferences"] == {
        "mode": "",
        "model": "",
        "reasoning_effort": "medium",
        "persisted": False,
    }

    saved = client.post(
        "/api/preferences",
        headers=HEADERS,
        json={"mode": "apply", "model": model, "reasoning_effort": "high"},
    )

    assert saved.status_code == 200
    assert saved.json()["preferences"] == {
        "mode": "apply",
        "model": model,
        "reasoning_effort": "high",
        "persisted": True,
    }

    status = client.get("/api/status", headers=HEADERS)

    assert status.status_code == 200
    assert status.json()["preferences"] == saved.json()["preferences"]


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-6-astra"])
def test_run_request_persists_preferences_before_auth_check(tmp_path, monkeypatch, model) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/runs",
        headers=HEADERS,
        json={
            "prompt": "Inspect the dashboard",
            "mode": "propose",
            "model": model,
        },
    )

    assert response.status_code == 401

    status = client.get("/api/status", headers=HEADERS)

    assert status.json()["preferences"] == {
        "mode": "propose",
        "model": model,
        "reasoning_effort": "medium",
        "persisted": True,
    }


def test_attachment_upload_converts_with_markitdown_and_stores_markdown(
    tmp_path,
    monkeypatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    from codex_agent import main

    monkeypatch.setattr(
        main,
        "_convert_attachment_with_markitdown",
        lambda path: f"# Converted\n\nsource: {path.suffix}",
    )

    response = client.post(
        "/api/attachments",
        headers=HEADERS,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    attachment = response.json()["attachment"]
    assert attachment["filename"] == "notes.txt"
    assert attachment["markdown_chars"] > 0

    stored = main.db.get_attachments("user-1", [attachment["id"]])
    assert stored[0]["markdown"] == "# Converted\n\nsource: .txt"
    assert stored[0]["kind"] == "markdown"
    assert stored[0]["file_path"] is None


def test_image_attachment_upload_stores_file_without_markitdown(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path)
    client = make_client(tmp_path, monkeypatch)
    from codex_agent import main

    monkeypatch.setattr(main, "ATTACHMENT_FILE_DIR", tmp_path / "attachments")
    monkeypatch.setattr(
        main,
        "_convert_attachment_with_markitdown",
        lambda _path: (_ for _ in ()).throw(AssertionError("MarkItDown should not run")),
    )

    response = client.post(
        "/api/attachments",
        headers=HEADERS,
        files={
            "file": (
                "WhatsApp Image 2026-07-10 at 17.47.21.jpeg",
                b"\xff\xd8\xff\xe0fake-jpeg",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 200
    attachment = response.json()["attachment"]
    assert attachment["kind"] == "image"
    assert attachment["markdown_chars"] == 0

    stored = main.db.get_attachments("user-1", [attachment["id"]])[0]
    assert stored["markdown"] == ""
    assert stored["kind"] == "image"
    stored_path = Path(stored["file_path"])
    assert stored_path.exists()
    assert stored_path.suffix == ".jpg"

    delete_response = client.delete(f"/api/attachments/{attachment['id']}", headers=HEADERS)

    assert delete_response.status_code == 200
    assert not stored_path.exists()


def test_run_request_passes_converted_attachments_to_runner(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    from codex_agent import main

    captured = {}
    monkeypatch.setattr(main.runner, "auth_status", lambda _user: {"configured": True})

    async def fake_start_run(
        user,
        prompt,
        mode,
        model,
        session_id,
        assessment,
        **kwargs,
    ) -> str:
        captured["user"] = user
        captured["prompt"] = prompt
        captured["attachments"] = kwargs["attachments"]
        captured["reasoning_effort"] = kwargs["reasoning_effort"]
        return "run-1"

    monkeypatch.setattr(main.runner, "start_run", fake_start_run)
    main.db.create_attachment(
        {
            "id": "attachment-1",
            "user_id": "user-1",
            "filename": "dashboard.pdf",
            "content_type": "application/pdf",
            "size_bytes": 42,
            "kind": "markdown",
            "file_path": None,
            "markdown": "# Dashboard\n\nlight.kitchen",
            "created_at": "2026-06-21T00:00:00+00:00",
        }
    )

    response = client.post(
        "/api/runs",
        headers=HEADERS,
        json={
            "prompt": "Read the attachment.",
            "mode": "ask",
            "model": "gpt-5.5",
            "reasoning_effort": "xhigh",
            "attachment_ids": ["attachment-1"],
        },
    )

    assert response.status_code == 200
    assert captured["prompt"] == "Read the attachment."
    assert captured["reasoning_effort"] == "xhigh"
    assert captured["attachments"][0]["filename"] == "dashboard.pdf"
    assert captured["attachments"][0]["markdown"] == "# Dashboard\n\nlight.kitchen"


@pytest.mark.parametrize("endpoint", ["/api/preferences", "/api/runs"])
@pytest.mark.parametrize(
    "model,effort,status",
    [
        ("gpt-6.1-sol", "ultra", 200),
        ("gpt-6-luna", "max", 200),
        ("gpt-6-luna", "ultra", 400),
        ("gpt-5.5", "max", 400),
        ("gpt-6-sol", "invalid", 422),
    ],
)
def test_reasoning_intensity_validated_for_model(
    tmp_path,
    monkeypatch,
    endpoint,
    model,
    effort,
    status,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    body = {"model": model, "reasoning_effort": effort, "prompt": "Inspect entities"}
    response = client.post(endpoint, headers=HEADERS, json=body)
    expected = 401 if endpoint == "/api/runs" and status == 200 else status
    assert response.status_code == expected


def test_old_preferences_default_to_medium_and_migrate_retired_models(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    from codex_agent import main

    main.db.set_state("user_preferences:user-1", {"mode": "ask", "model": "gpt-5.4-mini"})
    preferences = client.get("/api/status", headers=HEADERS).json()["preferences"]
    assert preferences["model"] == "gpt-6-luna"
    assert preferences["reasoning_effort"] == "medium"


def test_model_switch_resets_unsupported_intensity_and_preserves_user_scope(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    saved = client.post(
        "/api/preferences",
        headers=HEADERS,
        json={
            "model": "gpt-6.1-sol",
            "reasoning_effort": "ultra",
        },
    )
    assert saved.status_code == 200
    other_headers = {**HEADERS, "X-Remote-User-Id": "user-2"}
    other = client.get("/api/status", headers=other_headers).json()["preferences"]
    assert other["reasoning_effort"] == "medium"
    assert other["persisted"] is False
    switched = client.post("/api/preferences", headers=HEADERS, json={"model": "gpt-6-luna"})
    assert switched.status_code == 200
    assert switched.json()["preferences"]["reasoning_effort"] == "medium"


def test_approval_replay_runs_original_intensity_without_replacing_new_preferences(
    tmp_path,
    monkeypatch,
):
    client = make_client(tmp_path, monkeypatch)
    from codex_agent import main

    client.post(
        "/api/preferences",
        headers=HEADERS,
        json={
            "model": "gpt-6-luna",
            "reasoning_effort": "low",
        },
    )
    monkeypatch.setattr(main.runner, "auth_status", lambda _user: {"configured": True})
    captured = {}

    async def start_run(*args, **kwargs):
        captured["model"] = args[3]
        captured["effort"] = kwargs["reasoning_effort"]
        return "approved-run"

    monkeypatch.setattr(main.runner, "start_run", start_run)
    response = client.post(
        "/api/runs",
        headers=HEADERS,
        json={
            "prompt": "Inspect entities",
            "model": "gpt-6.1-sol",
            "reasoning_effort": "high",
            "approved": True,
        },
    )
    assert response.status_code == 200
    assert captured == {"model": "gpt-6.1-sol", "effort": "high"}
    preferences = client.get("/api/status", headers=HEADERS).json()["preferences"]
    assert preferences["model"] == "gpt-6-luna"
    assert preferences["reasoning_effort"] == "low"
