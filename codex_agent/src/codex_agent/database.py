from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .settings import DATA_DIR

DB_PATH = DATA_DIR / "codex_agent.sqlite3"


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    safe_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    approval_required INTEGER NOT NULL,
                    approved INTEGER NOT NULL,
                    yolo INTEGER NOT NULL,
                    secret_access_approved INTEGER NOT NULL,
                    backup_slug TEXT,
                    backup_job_id TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    exit_code INTEGER,
                    final_message TEXT,
                    diff TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    exit_code INTEGER
                );

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def upsert_user(self, user_id: str, username: str, display_name: str, safe_id: str) -> None:
        now = utcnow()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO users (
                    user_id, username, display_name, safe_id, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    last_seen_at = excluded.last_seen_at
                """,
                (user_id, username, display_name, safe_id, now, now),
            )

    def create_run(self, record: dict[str, Any]) -> None:
        columns = ", ".join(record)
        placeholders = ", ".join("?" for _ in record)
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO runs ({columns}) VALUES ({placeholders})",
                tuple(record.values()),
            )

    def update_run(self, run_id: str, **updates: Any) -> None:
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values())
        values.append(run_id)
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE runs SET {assignments} WHERE id = ?", values)

    def add_event(self, run_id: str, event_type: str, payload: dict[str, Any] | str) -> None:
        serialized = (
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (run_id, created_at, type, payload) VALUES (?, ?, ?, ?)",
                (run_id, utcnow(), event_type, serialized),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM runs
                WHERE user_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM events
                WHERE run_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (run_id, after_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_auth_job(self, job_id: str, user_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO auth_jobs (id, user_id, status, output, started_at)
                VALUES (?, ?, 'running', '', ?)
                """,
                (job_id, user_id, utcnow()),
            )

    def append_auth_output(self, job_id: str, text: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE auth_jobs SET output = output || ? WHERE id = ?",
                (text, job_id),
            )

    def finish_auth_job(self, job_id: str, status: str, exit_code: int | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE auth_jobs
                SET status = ?, exit_code = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, exit_code, utcnow(), job_id),
            )

    def get_auth_job(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM auth_jobs WHERE id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def get_state(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utcnow()),
            )

    def cleanup(self, retention_days: int) -> dict[str, int]:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff_s = cutoff.isoformat()
        deleted: dict[str, int] = {}
        with self._lock, self._conn:
            old_run_ids = [
                row["id"]
                for row in self._conn.execute(
                    "SELECT id FROM runs WHERE started_at < ?",
                    (cutoff_s,),
                ).fetchall()
            ]
            deleted["events"] = self._delete_events(old_run_ids)
            cur = self._conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff_s,))
            deleted["runs"] = cur.rowcount
            cur = self._conn.execute("DELETE FROM auth_jobs WHERE started_at < ?", (cutoff_s,))
            deleted["auth_jobs"] = cur.rowcount
        return deleted

    def _delete_events(self, run_ids: Iterable[str]) -> int:
        count = 0
        for run_id in run_ids:
            cur = self._conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            count += cur.rowcount
        return count
