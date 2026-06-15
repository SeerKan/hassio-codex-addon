from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("CODEX_AGENT_DATA", "/data"))
OPTIONS_PATH = DATA_DIR / "options.json"


@dataclass(frozen=True)
class Settings:
    retention_days: int = 30
    enable_live_search: bool = True
    allow_yolo_mode: bool = True
    create_backup_before_first_change: bool = True
    require_approval_for_secrets: bool = True
    codex_model: str = ""
    max_snapshot_file_kb: int = 512
    log_level: str = "info"


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def load_settings(path: Path = OPTIONS_PATH) -> Settings:
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)

    return Settings(
        retention_days=max(1, min(int(raw.get("retention_days", 30)), 365)),
        enable_live_search=_coerce_bool(raw.get("enable_live_search"), True),
        allow_yolo_mode=_coerce_bool(raw.get("allow_yolo_mode"), True),
        create_backup_before_first_change=_coerce_bool(
            raw.get("create_backup_before_first_change"), True
        ),
        require_approval_for_secrets=_coerce_bool(raw.get("require_approval_for_secrets"), True),
        codex_model=str(raw.get("codex_model", "") or ""),
        max_snapshot_file_kb=max(16, min(int(raw.get("max_snapshot_file_kb", 512)), 4096)),
        log_level=str(raw.get("log_level", "info") or "info"),
    )
