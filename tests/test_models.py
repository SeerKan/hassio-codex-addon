from codex_agent.models import CODEX_MODEL_IDS, CODEX_MODEL_OPTIONS, DEFAULT_CODEX_MODEL


def test_gpt_56_models_are_first_and_default_to_terra() -> None:
    assert [model["id"] for model in CODEX_MODEL_OPTIONS[:3]] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert DEFAULT_CODEX_MODEL == "gpt-5.6-terra"


def test_model_dropdown_stays_within_supported_limit() -> None:
    ids = [model["id"] for model in CODEX_MODEL_OPTIONS]

    assert len(ids) <= 10
    assert len(ids) == len(set(ids))
    assert set(ids) == CODEX_MODEL_IDS
