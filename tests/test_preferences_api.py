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
