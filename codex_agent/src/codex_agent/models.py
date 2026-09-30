from __future__ import annotations

from typing import Final, Literal, TypedDict

ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
DEFAULT_REASONING_EFFORT: Final[ReasoningEffort] = "medium"
REASONING_EFFORTS: Final[list[str]] = ["low", "medium", "high", "xhigh", "max", "ultra"]


class ModelOption(TypedDict):
    id: str
    label: str
    description: str
    reasoning_efforts: list[str]


CODEX_MODEL_OPTIONS: Final[list[ModelOption]] = [
    {
        "id": "gpt-6.1-sol",
        "label": "GPT-6.1 Sol",
        "description": (
            "Latest Sol model for complex coding and sustained work at lower cost than Astra."
        ),
        "reasoning_efforts": REASONING_EFFORTS.copy(),
    },
    {
        "id": "gpt-6-astra",
        "label": "GPT-6 Astra",
        "description": "Most capable model for complex Home Assistant work across code and tools.",
        "reasoning_efforts": REASONING_EFFORTS.copy(),
    },
    {
        "id": "gpt-6-sol",
        "label": "GPT-6 Sol",
        "description": "GPT-6 model for complex coding and agentic workflows.",
        "reasoning_efforts": REASONING_EFFORTS.copy(),
    },
    {
        "id": "gpt-6-luna",
        "label": "GPT-6 Luna",
        "description": "Efficient GPT-6 model for focused coding and high-volume tasks.",
        "reasoning_efforts": REASONING_EFFORTS[:-1],
    },
    {
        "id": "gpt-5.6-sol",
        "label": "GPT-5.6 Sol",
        "description": "Previous Sol model for complex Home Assistant coding and reasoning work.",
        "reasoning_efforts": REASONING_EFFORTS.copy(),
    },
    {
        "id": "gpt-5.6-terra",
        "label": "GPT-5.6 Terra",
        "description": (
            "Balanced GPT-5.6 option for everyday work across capability, speed, and cost."
        ),
        "reasoning_efforts": REASONING_EFFORTS.copy(),
    },
    {
        "id": "gpt-5.6-luna",
        "label": "GPT-5.6 Luna",
        "description": "Efficient GPT-5.6 option for focused coding tasks.",
        "reasoning_efforts": REASONING_EFFORTS[:-1],
    },
    {
        "id": "gpt-5.5",
        "label": "GPT-5.5",
        "description": "Previous-generation model; retires from Codex on October 14, 2026.",
        "reasoning_efforts": REASONING_EFFORTS[:4],
    },
]

DEFAULT_CODEX_MODEL: Final[str] = "gpt-5.6-terra"
CODEX_MODEL_IDS: Final[set[str]] = {model["id"] for model in CODEX_MODEL_OPTIONS}
MODEL_MIGRATIONS: Final[dict[str, str]] = {
    "gpt-5.4": "gpt-6-sol",
    "gpt-5.4-mini": "gpt-6-luna",
    "gpt-5.3-codex-spark": "gpt-6-luna",
}


def normalize_model(model: str | None) -> str | None:
    value = (model or "").strip()
    return MODEL_MIGRATIONS.get(value, value) or None


def reasoning_efforts_for_model(model: str) -> list[str]:
    return next(
        (option["reasoning_efforts"] for option in CODEX_MODEL_OPTIONS if option["id"] == model),
        [],
    )
