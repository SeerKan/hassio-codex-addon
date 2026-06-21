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


def test_user_preferences_round_trip(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    initial = client.get("/api/status", headers=HEADERS)

    assert initial.status_code == 200
    assert initial.json()["preferences"] == {"mode": "", "model": "", "persisted": False}

    saved = client.post(
        "/api/preferences",
        headers=HEADERS,
        json={"mode": "apply", "model": "gpt-5.4-mini"},
    )

    assert saved.status_code == 200
    assert saved.json()["preferences"] == {
        "mode": "apply",
        "model": "gpt-5.4-mini",
        "persisted": True,
    }

    status = client.get("/api/status", headers=HEADERS)

    assert status.status_code == 200
    assert status.json()["preferences"] == saved.json()["preferences"]


def test_run_request_persists_preferences_before_auth_check(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/runs",
        headers=HEADERS,
        json={
            "prompt": "Inspect the dashboard",
            "mode": "propose",
            "model": "gpt-5.4-mini",
        },
    )

    assert response.status_code == 401

    status = client.get("/api/status", headers=HEADERS)

    assert status.json()["preferences"] == {
        "mode": "propose",
        "model": "gpt-5.4-mini",
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
        return "run-1"

    monkeypatch.setattr(main.runner, "start_run", fake_start_run)
    main.db.create_attachment(
        {
            "id": "attachment-1",
            "user_id": "user-1",
            "filename": "dashboard.pdf",
            "content_type": "application/pdf",
            "size_bytes": 42,
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
            "attachment_ids": ["attachment-1"],
        },
    )

    assert response.status_code == 200
    assert captured["prompt"] == "Read the attachment."
    assert captured["attachments"][0]["filename"] == "dashboard.pdf"
    assert captured["attachments"][0]["markdown"] == "# Dashboard\n\nlight.kitchen"
