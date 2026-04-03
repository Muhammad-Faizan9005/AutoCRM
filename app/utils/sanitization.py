from __future__ import annotations

import re
from typing import Any


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(value: str) -> str:
    cleaned = _CONTROL_CHAR_RE.sub("", value)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    return _WHITESPACE_RE.sub(" ", cleaned)


def sanitize_payload(payload: dict[str, Any], skip_keys: set[str] | None = None) -> dict[str, Any]:
    skip_keys = skip_keys or set()
    sanitized: dict[str, Any] = {}

    for key, value in payload.items():
        if key in skip_keys:
            sanitized[key] = value
            continue

        if isinstance(value, str):
            sanitized[key] = sanitize_text(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [sanitize_text(item) if isinstance(item, str) else item for item in value]
        else:
            sanitized[key] = value

    return sanitized
