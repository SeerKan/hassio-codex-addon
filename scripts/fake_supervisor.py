from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "dev-supervisor-token")


def _states() -> list[dict[str, Any]]:
    return [
        {
            "entity_id": "light.camera_oaspeti_spot_1",
            "state": "off",
            "attributes": {"friendly_name": "Camera Oaspeti Spot 1"},
        },
        {
            "entity_id": "light.camera_oaspeti_spot_2",
            "state": "on",
            "attributes": {"friendly_name": "Camera Oaspeti Spot 2", "brightness": 255},
        },
        {
            "entity_id": "light.camera_oaspeti_spot_3",
            "state": "off",
            "attributes": {"friendly_name": "Camera Oaspeti Spot 3"},
        },
        {
            "entity_id": "light.camera_oaspeti_spot_4",
            "state": "off",
            "attributes": {"friendly_name": "Camera Oaspeti Spot 4"},
        },
        {
            "entity_id": "switch.test_plug",
            "state": "off",
            "attributes": {"friendly_name": "Test Plug"},
        },
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeSupervisor/1.0"

    def do_GET(self) -> None:  # noqa: N802
        routes: dict[str, Any] = {
            "/supervisor/info": {
                "version": "dev",
                "channel": "local",
                "supported": True,
                "healthy": True,
            },
            "/core/info": {
                "version": os.environ.get("HA_VERSION", "2026.6.0"),
                "machine": "local-dev",
                "state": "RUNNING",
            },
            "/host/info": {
                "operating_system": "Local Docker",
                "arch": os.uname().machine,
            },
            "/core/api/config": {
                "version": os.environ.get("HA_VERSION", "2026.6.0"),
                "location_name": "Local HA Test",
                "time_zone": "Europe/Bucharest",
                "components": ["light", "scene", "switch", "lovelace"],
            },
            "/core/api/states": _states(),
        }
        if self.path in routes:
            self._json(routes[self.path])
            return
        self._json({"error": f"Unknown fake supervisor path: {self.path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/backups/new/full":
            self._json(
                {
                    "slug": f"dev-backup-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                    "name": "Local dev backup",
                    "date": datetime.now(UTC).isoformat(),
                    "type": "full",
                }
            )
            return
        if self.path.startswith("/core/api/services/"):
            self._json({"context": {"id": "local-dev-context"}, "response": None})
            return
        self._json({"error": f"Unknown fake supervisor path: {self.path}"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _json(self, value: Any, status: int = 200) -> None:
        if not self._authorized():
            status = 401
            value = {"error": "Missing or invalid bearer token"}
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {TOKEN}"


if __name__ == "__main__":
    port = int(os.environ.get("FAKE_SUPERVISOR_PORT", "80"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Fake Supervisor listening on :{port}", flush=True)
    server.serve_forever()
