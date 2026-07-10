from __future__ import annotations

import re
from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


_APPROVAL_ID_REVIEW_RE = re.compile(
    r"\s*Review approval #[0-9a-fA-F-]+ in the AI Control Center\.?",
)


def _hide_approval_id_from_message(message: str) -> str:
    cleaned = _APPROVAL_ID_REVIEW_RE.sub("", message).strip()
    if not cleaned:
        return "Review in the AI Control Center."
    return f"{cleaned.rstrip('. ')}. Review in the AI Control Center."


def _normalize_legacy_notification(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "")
    message = str(row.get("message") or "")
    is_legacy_agent_approval = (
        str(row.get("type") or "") == "agent_approval"
        and "Review approval #" in message
        and "in the AI Control Center" in message
    )
    is_legacy_deal_risk_approval = (
        str(row.get("type") or "") == "agent_approval"
        and str(row.get("entity_type") or "") == "deal"
        and title.startswith("AI approval required: Deal risk alert")
        and "Deal risk detected" in message
        and "Review approval #" in message
    )
    if not is_legacy_deal_risk_approval:
        if is_legacy_agent_approval:
            normalized = dict(row)
            normalized["message"] = _hide_approval_id_from_message(message)
            return normalized
        return row

    normalized = dict(row)
    normalized["type"] = "agent_alert"
    normalized["title"] = "Deal risk alert"
    normalized["message"] = "Deal risk detected. Review stage progress, recent activity, owner follow-up, and next steps."
    return normalized


class NotificationRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="notifications", resource_name="Notification")

    async def list_for_user(
        self,
        *,
        recipient_id: str,
        skip: int = 0,
        limit: int = 50,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*").eq("recipient_id", recipient_id)
            if unread_only:
                query = query.is_("read_at", None)
            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list notifications") from exc

        return [_normalize_legacy_notification(row) for row in response.data or []]
