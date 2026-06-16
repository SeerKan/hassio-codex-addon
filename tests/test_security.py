from codex_agent.security import classify_prompt, is_secret_path


def test_low_risk_read_only_prompt() -> None:
    assessment = classify_prompt("What automations mention the kitchen?", "ask")

    assert assessment.level == "low"
    assert assessment.approval_required is False


def test_dashboard_count_question_stays_low_risk() -> None:
    assessment = classify_prompt("How many lights are on the main dashboard?", "ask")

    assert assessment.level == "low"
    assert assessment.approval_required is False


def test_apply_prompt_is_medium_without_approval() -> None:
    assessment = classify_prompt("Add a dashboard card for the thermostat", "apply")

    assert assessment.level == "medium"
    assert assessment.approval_required is False
    assert assessment.configuration_change is True


def test_apply_entity_control_is_not_configuration_change() -> None:
    assessment = classify_prompt("Turn on the kitchen lights", "apply")

    assert assessment.level == "medium"
    assert assessment.approval_required is False
    assert assessment.configuration_change is False


def test_apply_climate_control_is_not_configuration_change() -> None:
    assessment = classify_prompt("Set the hallway thermostat to 21", "apply")

    assert assessment.level == "medium"
    assert assessment.approval_required is False
    assert assessment.configuration_change is False


def test_apply_automation_edit_is_configuration_change() -> None:
    assessment = classify_prompt("Create an automation for the hallway light", "apply")

    assert assessment.level == "medium"
    assert assessment.approval_required is False
    assert assessment.configuration_change is True


def test_destructive_prompt_requires_approval() -> None:
    assessment = classify_prompt("Delete every automation and restart Home Assistant", "apply")

    assert assessment.level == "high"
    assert assessment.approval_required is True


def test_secret_prompt_requires_approval() -> None:
    assessment = classify_prompt("Read secrets.yaml and fix the token", "ask")

    assert assessment.level == "high"
    assert assessment.secret_access is True
    assert assessment.approval_required is True


def test_secret_prompt_can_be_preapproved() -> None:
    assessment = classify_prompt(
        "Read secrets.yaml and explain a reference",
        "ask",
        secret_access_approved=True,
    )

    assert assessment.approval_required is False


def test_yolo_is_critical_without_second_gate() -> None:
    assessment = classify_prompt("Change my dashboard", "apply", yolo=True)

    assert assessment.level == "critical"
    assert assessment.approval_required is False


def test_secret_path_detection() -> None:
    assert is_secret_path("/homeassistant/secrets.yaml")
    assert is_secret_path("/ssl/fullchain.key")
    assert not is_secret_path("/homeassistant/configuration.yaml")
