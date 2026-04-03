from __future__ import annotations

import re


_NAME_RE = re.compile(r"^[a-zA-Z0-9 .,'_-]+$")
_PHONE_RE = re.compile(r"^\+?[0-9()\-\s]{7,20}$")


def validate_person_name(value: str) -> str:
    if not _NAME_RE.match(value):
        raise ValueError("Name contains unsupported characters")
    return value


def validate_phone(value: str | None) -> str | None:
    if value is None:
        return None
    if not _PHONE_RE.match(value):
        raise ValueError("Phone number format is invalid")
    return value


def validate_no_dangerous_sql_tokens(value: str) -> str:
    lowered = value.lower()
    dangerous_tokens = [";--", "drop table", "truncate table", "alter table"]
    if any(token in lowered for token in dangerous_tokens):
        raise ValueError("Input contains blocked SQL tokens")
    return value
