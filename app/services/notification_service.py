from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation
from app.repositories.notification_repository import NotificationRepository


class NotificationService:
    def __init__(self, db: Client):
        self.db = db
        self.repository = NotificationRepository(db)

    async def create_notification(
        self,
        *,
        recipient_id: str | None,
        actor_id: str | None,
        type: str,
        title: str,
        message: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not recipient_id:
            return None
        if actor_id and recipient_id == actor_id:
            return None

        payload: dict[str, Any] = {
            "recipient_id": recipient_id,
            "actor_id": actor_id,
            "type": type,
            "title": title,
            "message": message,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        return await self.repository.create(payload)

    async def get_agent_name(self, agent_id: str | None) -> str | None:
        if not agent_id:
            return None

        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT full_name, email FROM agents WHERE id = :id"),
                    {"id": agent_id},
                ).mappings().first()
                if not row:
                    return None
                return str(row.get("full_name") or row.get("email") or "")

        name = await run_db_operation(_query)
        return name or None
