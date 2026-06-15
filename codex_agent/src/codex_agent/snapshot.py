from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .security import is_secret_path

DEFAULT_ROOTS = (
    Path("/homeassistant"),
    Path("/config"),
    Path("/addon_configs"),
    Path("/addons"),
    Path("/share"),
    Path("/media"),
    Path("/ssl"),
)

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".storage/tmp",
    "deps",
    "tts",
    "www/community",
    "node_modules",
}


@dataclass(frozen=True)
class FileSnapshot:
    sha256: str
    text: str | None


def _is_ignored(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    return any(part in normalized for part in IGNORED_DIRS) or is_secret_path(path)


def _read_text(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def collect_snapshot(
    roots: tuple[Path, ...] = DEFAULT_ROOTS,
    *,
    max_file_kb: int = 512,
) -> dict[str, FileSnapshot]:
    max_bytes = max_file_kb * 1024
    result: dict[str, FileSnapshot] = {}
    for root in roots:
        if not root.exists():
            continue
        for current_root, dirs, files in os.walk(root):
            current = Path(current_root)
            dirs[:] = [directory for directory in dirs if not _is_ignored(current / directory)]
            if _is_ignored(current):
                continue
            for filename in files:
                path = current / filename
                if _is_ignored(path) or not path.is_file():
                    continue
                try:
                    raw = path.read_bytes()
                except OSError:
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                text = None
                if len(raw) <= max_bytes and b"\x00" not in raw:
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = None
                result[str(path)] = FileSnapshot(sha256=digest, text=text)
    return result


def diff_snapshots(
    before: dict[str, FileSnapshot],
    after: dict[str, FileSnapshot],
    *,
    max_chars: int = 120_000,
) -> str:
    chunks: list[str] = []
    paths = sorted(set(before) | set(after))
    for path in paths:
        old = before.get(path)
        new = after.get(path)
        if old and new and old.sha256 == new.sha256:
            continue
        if old is None:
            if new and new.text is None:
                chunks.append(f"Added binary or large file: {path}\n")
            old_text = []
            new_text = (new.text or "").splitlines(keepends=True) if new else []
        elif new is None:
            chunks.append(f"Deleted file: {path}\n" if old.text is None else "")
            old_text = (old.text or "").splitlines(keepends=True)
            new_text = []
        elif old.text is None or new.text is None:
            chunks.append(f"Changed binary or large file: {path}\n")
            continue
        else:
            old_text = old.text.splitlines(keepends=True)
            new_text = new.text.splitlines(keepends=True)

        if (old and old.text is None) or (new and new.text is None):
            continue

        chunks.extend(
            difflib.unified_diff(
                old_text,
                new_text,
                fromfile=f"before{path}",
                tofile=f"after{path}",
            )
        )
        if sum(len(chunk) for chunk in chunks) > max_chars:
            chunks.append("\nDiff truncated because it exceeded the display limit.\n")
            break
    return "".join(chunks)
