from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

SUPERVISOR_URL = "http://supervisor"
CORE_API_URL = f"{SUPERVISOR_URL}/core/api"


class HomeAssistantClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def get_json(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{SUPERVISOR_URL}{path}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{SUPERVISOR_URL}{path}",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def core_api_get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{CORE_API_URL}{path}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def context(self) -> dict[str, Any]:
        context: dict[str, Any] = {"retrieved_at": datetime.now(UTC).isoformat()}
        for key, getter in {
            "supervisor": lambda: self.get_json("/supervisor/info"),
            "core": lambda: self.get_json("/core/info"),
            "host": lambda: self.get_json("/host/info"),
            "core_config": lambda: self.core_api_get("/config"),
        }.items():
            try:
                context[key] = await getter()
            except Exception as exc:  # pragma: no cover - depends on live HA
                context[key] = {"error": str(exc)}
        return context

    async def create_full_backup(self, name: str) -> dict[str, Any]:
        payload = {
            "name": name,
            "compressed": True,
            "location": None,
            "background": False,
        }
        return await self.post_json("/backups/new/full", payload)
