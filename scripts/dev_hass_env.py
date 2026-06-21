from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".dev" / "hass-env"
NETWORK = "hass-codex-dev"
ADDON_IMAGE = "hassio-codex-addon:dev"
SUPERVISOR_TOKEN = "dev-supervisor-token"
CONTAINERS = {
    "addon": "hass-codex-dev-addon",
    "ha": "hass-codex-dev-ha",
    "supervisor": "hass-codex-dev-supervisor",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local Docker Home Assistant add-on test rig."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="Build and start the local test rig.")
    up.add_argument("--skip-build", action="store_true", help="Reuse the existing add-on image.")
    up.add_argument(
        "--skip-ha",
        action="store_true",
        help="Skip the Home Assistant Core container.",
    )

    sub.add_parser("down", help="Stop and remove local test containers.")
    sub.add_parser("test", help="Run HTTP smoke checks against the local add-on.")
    sub.add_parser("logs", help="Show recent logs from local test containers.")

    args = parser.parse_args()
    if args.command == "up":
        up_env(skip_build=args.skip_build, skip_ha=args.skip_ha)
    elif args.command == "down":
        down_env()
    elif args.command == "test":
        smoke_test()
    elif args.command == "logs":
        logs()
    return 0


def up_env(*, skip_build: bool, skip_ha: bool) -> None:
    require_docker()
    prepare_state()
    ensure_network()
    if not skip_build:
        build_addon()

    remove_container(CONTAINERS["supervisor"])
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINERS["supervisor"],
            "--network",
            NETWORK,
            "--network-alias",
            "supervisor",
            "-e",
            f"SUPERVISOR_TOKEN={SUPERVISOR_TOKEN}",
            "-v",
            f"{ROOT / 'scripts' / 'fake_supervisor.py'}:/fake_supervisor.py:ro",
            "-p",
            "8098:80",
            "python:3.12-alpine",
            "python",
            "/fake_supervisor.py",
        ]
    )

    if not skip_ha:
        remove_container(CONTAINERS["ha"])
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                CONTAINERS["ha"],
                "--network",
                NETWORK,
                "-v",
                f"{STATE_DIR / 'homeassistant'}:/config",
                "-p",
                "8123:8123",
                "ghcr.io/home-assistant/home-assistant:stable",
            ]
        )

    remove_container(CONTAINERS["addon"])
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINERS["addon"],
            "--network",
            NETWORK,
            "-e",
            "ALLOW_DEV_AUTH=1",
            "-e",
            f"SUPERVISOR_TOKEN={SUPERVISOR_TOKEN}",
            "-v",
            f"{STATE_DIR / 'addon-data'}:/data",
            "-v",
            f"{STATE_DIR / 'homeassistant'}:/homeassistant",
            "-v",
            f"{STATE_DIR / 'addon-config'}:/config",
            "-p",
            "8099:8099",
            ADDON_IMAGE,
        ]
    )

    wait_for_url("http://127.0.0.1:8099/health")
    print("\nLocal test rig is ready:")
    print("- Add-on sidebar: http://127.0.0.1:8099/")
    print("- Fake Supervisor: http://127.0.0.1:8098/supervisor/info")
    if not skip_ha:
        print("- Home Assistant Core: http://127.0.0.1:8123/")
    print("\nRun `python3 scripts/dev_hass_env.py test` for smoke checks.")


def down_env() -> None:
    for name in CONTAINERS.values():
        remove_container(name)
    print("Stopped local test rig containers.")


def smoke_test() -> None:
    health = request_json("http://127.0.0.1:8099/health")
    status = request_json("http://127.0.0.1:8099/api/status")
    html = request_text("http://127.0.0.1:8099/")
    assert health["status"] == "ok"
    assert status["app_version"]
    assert "Sessions" in html
    assert "Run Codex" not in html
    assert "__APP_SCRIPT__" not in html
    assert "__APP_STYLES__" not in html
    assert "static/app.js?v=" not in html
    assert "static/styles.css?v=" not in html
    assert 'id="sessionsList"' in html
    assert 'id="attachButton"' in html
    assert 'id="fileInput" type="file" multiple hidden' in html
    assert 'id="attachmentTray"' in html
    print(f"Smoke checks passed for add-on {status['app_version']}.")


def logs() -> None:
    for name in CONTAINERS.values():
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            check=True,
            capture_output=True,
            text=True,
        )
        if name not in result.stdout.splitlines():
            continue
        print(f"\n== {name} ==")
        run(["docker", "logs", "--tail", "80", name], check=False)


def build_addon() -> None:
    arch = "aarch64" if platform.machine() in {"arm64", "aarch64"} else "amd64"
    run(
        [
            "docker",
            "buildx",
            "build",
            "--load",
            "--build-arg",
            "BUILD_VERSION=dev",
            "--build-arg",
            f"BUILD_ARCH={arch}",
            "-t",
            ADDON_IMAGE,
            str(ROOT / "codex_agent"),
        ]
    )


def prepare_state() -> None:
    (STATE_DIR / "homeassistant").mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "addon-data").mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "addon-config").mkdir(parents=True, exist_ok=True)
    config = STATE_DIR / "homeassistant" / "configuration.yaml"
    if not config.exists():
        config.write_text(
            "default_config:\n"
            "scene: !include scenes.yaml\n"
            "script: !include scripts.yaml\n",
            encoding="utf-8",
        )
    for name in ("scenes.yaml", "scripts.yaml"):
        path = STATE_DIR / "homeassistant" / name
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")


def ensure_network() -> None:
    result = subprocess.run(
        ["docker", "network", "inspect", NETWORK],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        run(["docker", "network", "create", NETWORK])


def remove_container(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_url(url: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request_text(url)
            return
        except (ConnectionResetError, urllib.error.URLError, TimeoutError):
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


def request_json(url: str) -> dict:
    import json

    return json.loads(request_text(url))


def request_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/json",
            "X-Remote-User-Id": "local-dev",
            "X-Remote-User-Name": "local-dev",
            "X-Remote-User-Display-Name": "Local Dev",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def require_docker() -> None:
    if not shutil.which("docker"):
        raise RuntimeError("Docker is required for the local Home Assistant add-on test rig.")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command))
    return subprocess.run(command, check=check, cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
