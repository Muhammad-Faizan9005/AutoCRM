from __future__ import annotations

LEAD_STATUSES = {"new", "qualified", "won", "lost"}
DEAL_STATUSES = {"qualified", "won", "lost"}
TASK_STATUSES = {"open", "backlog", "todo", "in_progress", "done", "canceled"}


def normalize_status(value: str | None, allowed: set[str]) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if cleaned not in allowed:
        raise ValueError(f"Unsupported status: {value}")
    return cleaned
