from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation


def _normalize_entity_type(value: str) -> str:
    return value.strip().lower()


def _normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


class StatusChangeLogService:
    def __init__(self, db: Client):
        self.db = db

    async def log_change(
        self,
        *,
        entity_type: str,
        entity_id: str,
        old_status: str | None,
        new_status: str,
        changed_by: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "entity_type": _normalize_entity_type(entity_type),
            "entity_id": entity_id,
            "old_status": _normalize_status(old_status),
            "new_status": _normalize_status(new_status) or "",
            "changed_by": changed_by,
        }

        def _exec():
            # The production PostgresClient exposes an SQLAlchemy engine. Tests and
            # some lightweight integrations provide only a Supabase-like table API,
            # so support both instead of making status logging break core CRM flows.
            engine = getattr(self.db, "engine", None)
            if engine is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO status_change_logs
                                (entity_type, entity_id, old_status, new_status, changed_by)
                            VALUES
                                (:entity_type, :entity_id, :old_status, :new_status, :changed_by)
                            """
                        ),
                        payload,
                    )
                return None

            self.db.table("status_change_logs").insert(payload).execute()
            return None

        await run_db_operation(_exec)
