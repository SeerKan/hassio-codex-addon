from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, Request

SECRET_PATH_PATTERNS = (
    "secrets.yaml",
    ".storage/auth",
    ".storage/cloud",
    ".storage/core.config_entries",
    ".storage/onboarding",
    "known_devices.yaml",
    "authorized_keys",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)

SECRET_WORDS = re.compile(
    r"\b(secret|secrets\.yaml|token|credential|password|passwd|private key|api key|mfa|"
    r"refresh token|auth\.json)\b",
    re.IGNORECASE,
)

HIGH_RISK_WORDS = re.compile(
    r"\b(delete|remove|purge|wipe|destroy|factory reset|format|drop|erase|restore backup|"
    r"partial restore|full restore|shutdown|reboot host|disable auth|disable mfa|open port|"
    r"expose supervisor|chmod 777|chown -R|rm -rf)\b",
    re.IGNORECASE,
)

WRITE_WORDS = re.compile(
    r"\b(change|modify|edit|write|create|add|install|update|upgrade|reload|restart)\b",
    re.IGNORECASE,
)

CONFIG_WRITE_WORDS = re.compile(
    r"\b(add|create|configure|delete|edit|enable|disable|fix|hide|install|migrate|modify|"
    r"move|remove|rename|reorder|repair|replace|set up|setup|show|update|write|change)\b",
    re.IGNORECASE,
)

CONFIG_TARGET_WORDS = re.compile(
    r"\b(add-?on|addon|area|automation|blueprint|card|config|configuration|custom component|"
    r"dashboard|device registry|entity registry|frontend|group|hacs|helper|input_boolean|"
    r"input_datetime|input_number|input_select|input_text|integration|layout|lovelace|package|"
    r"panel|scene|script|sensor config|sidebar|template|theme|ui|view|yaml|zone)\b",
    re.IGNORECASE,
)

CONFIG_FILE_WORDS = re.compile(
    r"(/homeassistant|\.storage|configuration\.ya?ml|automations\.ya?ml|scripts\.ya?ml|"
    r"scenes\.ya?ml|ui-lovelace\.ya?ml|dashboards?/|\.ya?ml\b|\.json\b)",
    re.IGNORECASE,
)

RUNTIME_ACTION_WORDS = re.compile(
    r"\b(activate|arm|call service|close|disarm|lock|open|press|run|set|set temperature|"
    r"start|stop|toggle|turn off|turn on|unlock)\b",
    re.IGNORECASE,
)

RUNTIME_DOMAIN_WORDS = re.compile(
    r"\b(alarm|button|climate|cover|fan|humidifier|input button|light|lock|media player|"
    r"scene|script|switch|thermostat|vacuum)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UserContext:
    user_id: str
    username: str
    display_name: str

    @property
    def safe_id(self) -> str:
        digest = hashlib.sha256(self.user_id.encode("utf-8")).hexdigest()[:32]
        return digest


@dataclass(frozen=True)
class RiskAssessment:
    level: str
    approval_required: bool
    secret_access: bool = False
    configuration_change: bool = False
    reasons: list[str] = field(default_factory=list)
    warning: str = ""


def classify_prompt(
    prompt: str,
    mode: str,
    *,
    yolo: bool = False,
    secret_access_approved: bool = False,
    require_approval_for_secrets: bool = True,
) -> RiskAssessment:
    normalized = prompt.strip()
    reasons: list[str] = []
    secret_access = bool(SECRET_WORDS.search(normalized))
    destructive = bool(HIGH_RISK_WORDS.search(normalized))
    writes = mode == "apply" or bool(WRITE_WORDS.search(normalized))
    configuration_change = detect_configuration_change(normalized, mode)

    if yolo:
        return RiskAssessment(
            level="critical",
            approval_required=False,
            secret_access=secret_access,
            configuration_change=configuration_change,
            reasons=["Full-auto mode bypasses Codex approvals and sandboxing."],
            warning=(
                "Full-auto mode can make broad changes without additional prompts. "
                "Make sure you can restore from backup."
            ),
        )

    if secret_access and require_approval_for_secrets and not secret_access_approved:
        reasons.append("The request appears to need secrets, credentials, or token access.")

    if destructive:
        reasons.append("The request contains destructive or high-impact operations.")

    if reasons:
        return RiskAssessment(
            level="high",
            approval_required=True,
            secret_access=secret_access,
            configuration_change=configuration_change,
            reasons=reasons,
            warning="High-risk Home Assistant changes require explicit approval.",
        )

    if writes:
        change_type = (
            "configuration"
            if configuration_change
            else "runtime state"
        )
        return RiskAssessment(
            level="medium",
            approval_required=False,
            secret_access=secret_access,
            configuration_change=configuration_change,
            reasons=[f"The request may change Home Assistant {change_type}."],
        )

    return RiskAssessment(
        level="low",
        approval_required=False,
        secret_access=secret_access,
        configuration_change=configuration_change,
        reasons=["Read-only or low-impact request."],
    )


def detect_configuration_change(prompt: str, mode: str) -> bool:
    if mode != "apply":
        return False

    normalized = prompt.strip()
    if not normalized:
        return False

    writes_config_target = bool(CONFIG_WRITE_WORDS.search(normalized)) and bool(
        CONFIG_TARGET_WORDS.search(normalized)
    )
    writes_config_file = bool(CONFIG_WRITE_WORDS.search(normalized)) and bool(
        CONFIG_FILE_WORDS.search(normalized)
    )
    if writes_config_target or writes_config_file:
        return True

    runtime_action = bool(RUNTIME_ACTION_WORDS.search(normalized)) and bool(
        RUNTIME_DOMAIN_WORDS.search(normalized)
    )
    if runtime_action:
        return False

    return False


def is_secret_path(path: Path | str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(pattern in normalized for pattern in SECRET_PATH_PATTERNS)


def user_from_request(request: Request) -> UserContext:
    user_id = request.headers.get("x-remote-user-id")
    username = request.headers.get("x-remote-user-name") or "unknown"
    display_name = request.headers.get("x-remote-user-display-name") or username

    if not user_id and os.environ.get("ALLOW_DEV_AUTH") == "1":
        user_id = "local-dev"
        username = "local-dev"
        display_name = "Local Dev"

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="This endpoint must be accessed through authenticated Home Assistant ingress.",
        )

    return UserContext(user_id=user_id, username=username, display_name=display_name)
