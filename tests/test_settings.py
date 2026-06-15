import json

from codex_agent.settings import load_settings


def test_load_settings_defaults(tmp_path) -> None:
    settings = load_settings(tmp_path / "missing.json")

    assert settings.retention_days == 30
    assert settings.enable_live_search is True


def test_load_settings_clamps_values(tmp_path) -> None:
    path = tmp_path / "options.json"
    path.write_text(
        json.dumps(
            {
                "retention_days": 999,
                "enable_live_search": "false",
                "max_snapshot_file_kb": 99999,
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.retention_days == 365
    assert settings.enable_live_search is False
    assert settings.max_snapshot_file_kb == 4096
