from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from supabase import Client

from app.repositories.base import BaseRepository


class AgentRunRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_runs", resource_name="AI Agent Run")

    async def find_by_external_id(self, external_run_id: str) -> dict[str, Any] | None:
        return await self.find_one(filters={"external_run_id": external_run_id})


class AgentTraceRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_run_traces", resource_name="AI Agent Run Trace")

    async def list_for_run(self, run_id: UUID | str) -> list[dict[str, Any]]:
        return await self.list(filters={"run_id": str(run_id)}, order_by="created_at")


class AgentActionRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_actions", resource_name="AI Agent Action")

    async def mark_dispatched(
        self,
        action_id: UUID | str,
        *,
        crm_record_type: str,
        crm_record_id: str | None,
    ) -> dict[str, Any]:
        return await self.update_by_id(
            action_id,
            {
                "approval_status": "approved",
                "dispatch_status": "dispatched",
                "crm_record_type": crm_record_type,
                "crm_record_id": crm_record_id,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        )


class AgentApprovalRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_approval_requests", resource_name="AI Agent Approval")

    async def list_pending(self) -> list[dict[str, Any]]:
        return await self.list(filters={"state": "pending"}, order_by="created_at")


class AgentSettingRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_settings", resource_name="AI Agent Setting")

    async def list_settings(self) -> list[dict[str, Any]]:
        return await self.list(order_by="agent_type")

    async def find_by_agent_type(self, agent_type: str) -> dict[str, Any] | None:
        return await self.find_one(filters={"agent_type": agent_type})


# ---------------------------------------------------------------------------
# AI Agents Registry  (permanent source of truth — NOT the human agents table)
# ---------------------------------------------------------------------------

class AiAgentRepository(BaseRepository):
    """Registry of AI worker identities used by the AI Control Center."""

    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agents", resource_name="AI Agent")

    async def find_by_key(self, agent_key: str) -> dict[str, Any] | None:
        return await self.find_one(filters={"agent_key": agent_key})

    async def list_all(self) -> list[dict[str, Any]]:
        return await self.list(order_by="display_name")

    async def list_enabled(self) -> list[dict[str, Any]]:
        return await self.list(filters={"enabled": True}, order_by="display_name")


class AiAgentCredentialRepository(BaseRepository):
    """Hashed service-token credentials linked to ai_agents."""

    def __init__(self, db: Client):
        super().__init__(db=db, table_name="ai_agent_credentials", resource_name="AI Agent Credential")

    async def list_for_agent(self, ai_agent_id: str) -> list[dict[str, Any]]:
        return await self.list(filters={"ai_agent_id": ai_agent_id}, order_by="created_at", order_desc=True)

    async def find_active_by_hash(self, ai_agent_id: str, token_hash: str) -> dict[str, Any] | None:
        """Find the first active credential matching the given token hash."""
        results = await self.list(
            filters={"ai_agent_id": ai_agent_id, "token_hash": token_hash, "is_active": True},
            limit=1,
        )
        return results[0] if results else None
