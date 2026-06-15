from pathlib import Path

from codex_agent.snapshot import collect_snapshot, diff_snapshots


def test_snapshot_diff_excludes_secret_files(tmp_path: Path) -> None:
    root = tmp_path / "homeassistant"
    root.mkdir()
    (root / "configuration.yaml").write_text("a: 1\n", encoding="utf-8")
    (root / "secrets.yaml").write_text("password: old\n", encoding="utf-8")

    before = collect_snapshot((root,), max_file_kb=16)
    (root / "configuration.yaml").write_text("a: 2\n", encoding="utf-8")
    (root / "secrets.yaml").write_text("password: new\n", encoding="utf-8")
    after = collect_snapshot((root,), max_file_kb=16)

    diff = diff_snapshots(before, after)

    assert "configuration.yaml" in diff
    assert "secrets.yaml" not in diff
