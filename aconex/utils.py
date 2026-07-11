from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
import shutil
import json
from typing import Any


SENSITIVE_HEADER_NAMES = {"authorization", "cookie", "set-cookie", "x-xsrf-token"}
SENSITIVE_KEYS = {"client_secret", "access_token", "refresh_token", "id_token", "cookie"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def display_date(value: object) -> str:
    """Return the date component of an ISO-like timestamp for report displays."""
    text = str(value or "").strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else text


def safe_slug(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return (cleaned or "response")[:max_length]


def preview_text(content: bytes, length: int = 300) -> str:
    text = content[:length].decode("utf-8", errors="replace")
    return " ".join(text.split())


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS or key.lower() in SENSITIVE_HEADER_NAMES:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def token_hint(token: str) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 12:
        return f"<{len(token)} chars>"
    return f"{token[:6]}...{token[-4:]} ({len(token)} chars)"


def update_env_tokens(env_path: Path, *, refresh_token: str) -> Path:
    backup_path = env_path.with_name(f"{env_path.name}.bak.{utc_stamp()}")
    shutil.copy2(env_path, backup_path)

    updates = {
        "ACONEX_REFRESH_TOKEN": refresh_token,
        "ACONEX_AUTHORIZATION_CODE": "",
        "ACONEX_ACCESS_TOKEN": "",
    }
    seen: set[str] = set()
    output_lines: list[str] = []

    for line in env_path.read_text(encoding="utf-8").splitlines(keepends=True):
        line_ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if line_ending else line
        stripped = body.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in body:
            output_lines.append(line)
            continue

        key = body.split("=", 1)[0].strip()
        if key in updates:
            output_lines.append(f"{key}={updates[key]}{line_ending}")
            seen.add(key)
        else:
            output_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            if output_lines and not output_lines[-1].endswith("\n"):
                output_lines[-1] = f"{output_lines[-1]}\n"
            output_lines.append(f"{key}={value}\n")

    env_path.write_text("".join(output_lines), encoding="utf-8")
    return backup_path
