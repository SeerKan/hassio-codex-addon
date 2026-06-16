from __future__ import annotations

from typing import Final

CODEX_MODEL_OPTIONS: Final[list[dict[str, str]]] = [
    {
        "id": "gpt-5.5",
        "label": "GPT-5.5",
        "description": "Newest frontier model; best default for complex Home Assistant work.",
    },
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4",
        "description": "Flagship model for professional coding, reasoning, and tool use.",
    },
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 Mini",
        "description": "Faster option for lighter coding tasks and quick inspections.",
    },
    {
        "id": "gpt-5.3-codex-spark",
        "label": "GPT-5.3 Codex Spark",
        "description": "Fast research-preview coding iteration model for eligible Pro users.",
    },
]

DEFAULT_CODEX_MODEL: Final[str] = CODEX_MODEL_OPTIONS[0]["id"]
CODEX_MODEL_IDS: Final[set[str]] = {model["id"] for model in CODEX_MODEL_OPTIONS}


def normalize_model(model: str | None) -> str | None:
    value = (model or "").strip()
    return value or None

