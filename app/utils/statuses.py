from __future__ import annotations

LEAD_STATUSES = {"new", "contacted", "nurture", "qualified", "unqualified", "junk"}
DEAL_STATUSES = {"qualified", "qualification", "demo_making", "proposal_quotation", "negotiation", "ready_to_close", "won"}
TASK_STATUSES = {"backlog", "todo", "in_progress", "done", "canceled"}

STATUS_ALIASES = {
    "cancelled": "canceled",
    "open": "todo",
    "demo": "demo_making",
    "demo/making": "demo_making",
    "demo_making": "demo_making",
    "proposal": "proposal_quotation",
    "proposal/quotation": "proposal_quotation",
    "proposal_quotation": "proposal_quotation",
    "ready_to_close": "ready_to_close",
}


def normalize_status(value: str | None, allowed: set[str]) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    cleaned = raw.replace("/", "_").replace(" ", "_").replace("-", "_")
    cleaned = STATUS_ALIASES.get(raw, STATUS_ALIASES.get(cleaned, cleaned))
    if cleaned not in allowed:
        raise ValueError(f"Unsupported status: {value}")
    return cleaned
