from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "codex_agent"


def main() -> None:
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
    config = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))

    for key in ("name",):
        assert key in repository, f"repository.yaml missing {key}"

    required = {"name", "version", "slug", "description", "arch", "image"}
    missing = required - set(config)
    assert not missing, f"config.yaml missing {sorted(missing)}"

    assert set(config["arch"]) == {"amd64", "aarch64"}
    assert config["ingress"] is True
    assert config["panel_admin"] is True
    assert config["hassio_role"] == "admin"
    assert config["homeassistant_api"] is True
    assert config["hassio_api"] is True
    assert (ADDON / "Dockerfile").exists()
    assert (ADDON / "DOCS.md").exists()
    assert (ADDON / "README.md").exists()


if __name__ == "__main__":
    main()
