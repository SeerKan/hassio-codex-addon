from codex_agent.models import CODEX_MODEL_IDS, CODEX_MODEL_OPTIONS, DEFAULT_CODEX_MODEL


def test_latest_models_are_listed_and_default_stays_terra() -> None:
    assert [model["id"] for model in CODEX_MODEL_OPTIONS[:4]] == [
        "gpt-6.1-sol",
        "gpt-6-astra",
        "gpt-6-sol",
        "gpt-6-luna",
    ]
    assert DEFAULT_CODEX_MODEL == "gpt-5.6-terra"
    assert not {"gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"} & CODEX_MODEL_IDS


def test_model_dropdown_stays_within_supported_limit() -> None:
    ids = [model["id"] for model in CODEX_MODEL_OPTIONS]

    assert len(ids) <= 10
    assert len(ids) == len(set(ids))
    assert set(ids) == CODEX_MODEL_IDS
