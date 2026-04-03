from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError, ResourceNotFoundError
from app.repositories.base import BaseRepository


class TicketRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="tickets", resource_name="Ticket")

    async def list_tickets(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        priority: str | None = None,
        customer_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if priority:
            filters["priority"] = priority
        if customer_id:
            filters["customer_id"] = customer_id

        return await self.list(
            skip=skip,
            limit=limit,
            filters=filters if filters else None,
            order_by="created_at",
            order_desc=True,
        )

    async def list_ticket_messages(self, ticket_id: str) -> list[dict[str, Any]]:
        try:
            response = await run_db_operation(
                lambda: self.db.table("ticket_messages")
                .select("*")
                .eq("ticket_id", ticket_id)
                .order("created_at")
                .execute()
            )
        except Exception as exc:
            raise DatabaseError(detail="Failed to list ticket messages") from exc

        return response.data or []

    async def create_ticket_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await run_db_operation(lambda: self.db.table("ticket_messages").insert(payload).execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to create ticket message") from exc

        rows = response.data or []
        if not rows:
            raise ResourceNotFoundError("Ticket", payload.get("ticket_id"))
        return rows[0]
