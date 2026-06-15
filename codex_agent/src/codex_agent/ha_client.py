from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

SUPERVISOR_URL = "http://supervisor"
CORE_API_URL = f"{SUPERVISOR_URL}/core/api"


class HomeAssistantClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @property
    def token_available(self) -> bool:
        return bool(self.token)

    async def get_json(self, path: str) -> dict[str, Any]:
        if not self.token_available:
            raise RuntimeError("SUPERVISOR_TOKEN is not available in this environment.")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{SUPERVISOR_URL}{path}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token_available:
            raise RuntimeError("SUPERVISOR_TOKEN is not available in this environment.")
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{SUPERVISOR_URL}{path}",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def core_api_get(self, path: str) -> dict[str, Any]:
        if not self.token_available:
            raise RuntimeError("SUPERVISOR_TOKEN is not available in this environment.")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{CORE_API_URL}{path}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            "retrieved_at": datetime.now(UTC).isoformat(),
            "supervisor_token_available": self.token_available,
        }
        for key, getter in {
            "supervisor": lambda: self.get_json("/supervisor/info"),
            "core": lambda: self.get_json("/core/info"),
            "host": lambda: self.get_json("/host/info"),
            "core_config": lambda: self.core_api_get("/config"),
            "entity_states": lambda: self.core_api_get("/states"),
        }.items():
            try:
                value = await getter()
                context[key] = self._summarize_states(value) if key == "entity_states" else value
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

    @staticmethod
    def _summarize_states(value: Any) -> dict[str, Any]:
        if not isinstance(value, list):
            return {"error": "Unexpected Home Assistant states response."}

        counts: dict[str, int] = {}
        sample_entities: dict[str, list[str]] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str) or "." not in entity_id:
                continue
            domain = entity_id.split(".", 1)[0]
            counts[domain] = counts.get(domain, 0) + 1
            sample_entities.setdefault(domain, [])
            if len(sample_entities[domain]) < 12:
                sample_entities[domain].append(entity_id)

        return {
            "count": len(value),
            "domain_counts": dict(sorted(counts.items())),
            "sample_entities": {key: sample_entities[key] for key in sorted(sample_entities)},
        }
