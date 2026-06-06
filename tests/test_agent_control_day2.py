from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.routers.agent import (
    _build_team_agent_stats,
    _ensure_agent_settings,
    _legacy_interaction_as_trace,
    _list_legacy_ai_actions,
    _list_legacy_ai_interactions,
    _list_legacy_ai_runs,
    approve_agent_action,
    dispatch_agent_action,
)
from app.schemas.agent_action import AgentActionIn, AgentApprovalDecision


class FakeActionRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def find_one(self, *, filters: dict[str, Any]) -> dict[str, Any] | None:
        for row in self.rows:
            if all(str(row.get(key)) == str(value) for key, value in filters.items()):
                return row
        return None

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": str(uuid4()), **payload}
        self.rows.append(row)
        return row

    async def get_by_id(self, record_id) -> dict[str, Any]:
        for row in self.rows:
            if str(row["id"]) == str(record_id):
                return row
        raise KeyError(record_id)

    async def update_by_id(self, record_id, payload: dict[str, Any]) -> dict[str, Any]:
        row = await self.get_by_id(record_id)
        row.update(payload)
        return row

    async def mark_dispatched(self, action_id, *, crm_record_type: str, crm_record_id: str | None):
        return await self.update_by_id(
            action_id,
            {
                "approval_status": "approved",
                "dispatch_status": "dispatched",
                "crm_record_type": crm_record_type,
                "crm_record_id": crm_record_id,
            },
        )


class FakeApprovalRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": str(uuid4()), **payload}
        self.rows.append(row)
        return row

    async def get_by_id(self, record_id) -> dict[str, Any]:
        for row in self.rows:
            if str(row["id"]) == str(record_id):
                return row
        raise KeyError(record_id)

    async def update_by_id(self, record_id, payload: dict[str, Any]) -> dict[str, Any]:
        row = await self.get_by_id(record_id)
        row.update(payload)
        return row


class FakeRunRepository:
    async def find_by_external_id(self, _external_run_id: str):
        return None

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": str(uuid4()), **payload}


class FakeSettingRepository:
    def __init__(self):
        self.rows = []

    async def list_settings(self):
        return list(self.rows)

    async def create(self, payload):
        row = {"id": str(uuid4()), **payload}
        self.rows.append(row)
        return row

    async def find_by_agent_type(self, agent_type):
        for row in self.rows:
            if row["agent_type"] == agent_type:
                return row
        return None

    async def update_by_id(self, record_id, payload):
        for row in self.rows:
            if str(row["id"]) == str(record_id):
                row.update(payload)
                return row
        raise KeyError(record_id)


class FakeTaskRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": str(uuid4()), **payload}
        self.created.append(row)
        return row


class FakeNoteRepository:
    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": str(uuid4()), **payload}


class FakeNotificationService:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create_notification(self, **payload):
        row = {"id": str(uuid4()), **payload}
        self.created.append(row)
        return row


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeLegacyTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.order_by = None
        self.order_desc = False
        self.limit_value = None

    def select(self, *_args):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self.order_by = column
        self.order_desc = desc
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        rows = [
            row.copy()
            for row in self.rows
            if all(str(row.get(column)) == str(value) for column, value in self.filters)
        ]
        if self.order_by:
            rows.sort(key=lambda row: str(row.get(self.order_by) or ""), reverse=self.order_desc)
        if self.limit_value:
            rows = rows[: self.limit_value]
        return FakeResponse(rows)


class FakeLegacyDB:
    def __init__(self, tables):
        self.tables = tables

    def table(self, table_name):
        if table_name not in self.tables:
            raise KeyError(table_name)
        return FakeLegacyTable(self.tables[table_name])


def test_safe_agent_task_is_stored_and_dispatched() -> None:
    action_repo = FakeActionRepository()
    task_repo = FakeTaskRepository()
    user = {"id": str(uuid4()), "role": "sales_rep"}
    entity_id = uuid4()

    response = asyncio.run(
        dispatch_agent_action(
            AgentActionIn(
                action_type="create_task",
                entity_type="lead",
                entity_id=entity_id,
                reason="Lead needs follow-up",
                data={"title": "Call lead", "description": "Ask about timeline"},
                idempotency_key="task-1",
            ),
            current_user=user,
            run_repository=FakeRunRepository(),
            action_repository=action_repo,
            approval_repository=FakeApprovalRepository(),
            task_repository=task_repo,
            note_repository=FakeNoteRepository(),
            notification_service=FakeNotificationService(),
        )
    )

    assert response.status == "created"
    assert task_repo.created[0]["title"] == "Call lead"
    assert action_repo.rows[0]["dispatch_status"] == "dispatched"


def test_risky_agent_alert_is_stored_for_approval_without_dispatch() -> None:
    action_repo = FakeActionRepository()
    approval_repo = FakeApprovalRepository()
    notifications = FakeNotificationService()
    user = {"id": str(uuid4()), "role": "sales_rep"}

    response = asyncio.run(
        dispatch_agent_action(
            AgentActionIn(
                action_type="create_alert",
                entity_type="deal",
                entity_id=uuid4(),
                reason="Deal risk",
                data={"title": "Risk", "message": "Deal stalled", "recipient_id": str(uuid4())},
                requires_approval=True,
            ),
            current_user=user,
            run_repository=FakeRunRepository(),
            action_repository=action_repo,
            approval_repository=approval_repo,
            task_repository=FakeTaskRepository(),
            note_repository=FakeNoteRepository(),
            notification_service=notifications,
        )
    )

    assert response.status == "pending_approval"
    assert action_repo.rows[0]["approval_status"] == "pending"
    assert approval_repo.rows[0]["state"] == "pending"
    assert notifications.created == []


def test_approval_executes_pending_alert() -> None:
    action_repo = FakeActionRepository()
    approval_repo = FakeApprovalRepository()
    notifications = FakeNotificationService()
    manager = {"id": str(uuid4()), "role": "sales_manager"}
    action = asyncio.run(
        action_repo.create(
            {
                "action_type": "create_alert",
                "entity_type": "deal",
                "entity_id": str(uuid4()),
                "reason": "Deal risk",
                "payload": {"title": "Risk", "message": "Deal stalled", "recipient_id": str(uuid4())},
                "approval_status": "pending",
                "dispatch_status": "not_dispatched",
            }
        )
    )
    approval = asyncio.run(approval_repo.create({"action_id": action["id"], "state": "pending"}))

    response = asyncio.run(
        approve_agent_action(
            approval_id=approval["id"],
            decision=AgentApprovalDecision(note="Looks valid"),
            current_user=manager,
            approval_repository=approval_repo,
            action_repository=action_repo,
            task_repository=FakeTaskRepository(),
            note_repository=FakeNoteRepository(),
            notification_service=notifications,
        )
    )

    assert response["status"] == "approved"
    assert notifications.created[0]["type"] == "agent_alert"
    assert action_repo.rows[0]["dispatch_status"] == "dispatched"


def test_agent_action_validation_rejects_missing_alert_recipient() -> None:
    with pytest.raises(Exception):
        asyncio.run(
            dispatch_agent_action(
                AgentActionIn(
                    action_type="create_alert",
                    entity_type="deal",
                    entity_id=uuid4(),
                    reason="Deal risk",
                    data={"title": "Risk"},
                ),
                current_user={"id": str(uuid4()), "role": "sales_rep"},
                run_repository=FakeRunRepository(),
                action_repository=FakeActionRepository(),
                approval_repository=FakeApprovalRepository(),
                task_repository=FakeTaskRepository(),
                note_repository=FakeNoteRepository(),
                notification_service=FakeNotificationService(),
            )
        )


def test_legacy_ai_runs_are_mapped_for_control_center() -> None:
    run_id = str(uuid4())
    db = FakeLegacyDB(
        {
            "ai_runs": [
                {
                    "id": run_id,
                    "trigger_type": "stale_lead",
                    "entity_id": str(uuid4()),
                    "entity_type": "lead",
                    "status": "completed",
                    "summary": "old run",
                    "started_at": "2026-06-01T10:00:00Z",
                    "finished_at": "2026-06-01T10:00:01Z",
                }
            ]
        }
    )

    rows = asyncio.run(_list_legacy_ai_runs(db, {"status": None, "entity_type": None, "entity_id": None}))

    assert rows[0]["id"] == run_id
    assert rows[0]["legacy_source"] == "ai_service.ai_runs"


def test_legacy_ai_actions_are_mapped_as_entity_memory() -> None:
    entity_id = uuid4()
    db = FakeLegacyDB(
        {
            "ai_actions": [
                {
                    "id": str(uuid4()),
                    "run_id": str(uuid4()),
                    "action_type": "create_task",
                    "entity_type": "lead",
                    "entity_id": str(entity_id),
                    "reason": "old action",
                    "payload": {"title": "Call"},
                    "approval_status": "auto_approved",
                    "created_at": "2026-06-01T10:00:00Z",
                }
            ]
        }
    )

    rows = asyncio.run(_list_legacy_ai_actions(db, "lead", entity_id))

    assert rows[0]["action_type"] == "create_task"
    assert rows[0]["dispatch_status"] == "legacy"


def test_legacy_ai_interaction_is_visible_as_run_and_trace() -> None:
    interaction_id = uuid4()
    db = FakeLegacyDB(
        {
            "ai_interactions": [
                {
                    "id": str(interaction_id),
                    "ticket_id": str(uuid4()),
                    "interaction_type": "ticket_summary",
                    "prompt": "Summarize",
                    "response": "Summary",
                    "model_used": "legacy-model",
                    "tokens_used": 12,
                    "created_at": "2026-05-30T09:00:00Z",
                }
            ]
        }
    )

    runs = asyncio.run(_list_legacy_ai_interactions(db, {"status": None, "entity_type": None, "entity_id": None}))
    trace = asyncio.run(_legacy_interaction_as_trace(db, interaction_id))

    assert runs[0]["legacy_source"] == "backend.ai_interactions"
    assert trace[0]["payload"]["response"] == "Summary"


def test_agent_settings_defaults_are_created() -> None:
    repo = FakeSettingRepository()

    rows = asyncio.run(_ensure_agent_settings(repo))

    assert {row["agent_type"] for row in rows} == {
        "lead_assistant",
        "deal_risk_watcher",
        "daily_summary_assistant",
    }
    assert all(row["enabled"] is True for row in rows)


def test_team_stats_maps_manager_to_sales_rep_ai_activity() -> None:
    manager_id = str(uuid4())
    rep_id = str(uuid4())
    team_id = str(uuid4())
    db = FakeLegacyDB(
        {
            "agents": [
                {"id": manager_id, "full_name": "Manager", "email": "m@example.com", "role": "sales_manager"},
                {"id": rep_id, "full_name": "Rep", "email": "r@example.com", "role": "sales_rep", "team_id": team_id},
            ],
            "teams": [{"id": team_id, "name": "Team A", "manager_id": manager_id}],
            "team_members": [{"team_id": team_id, "agent_id": rep_id}],
            "ai_agent_actions": [
                {
                    "id": str(uuid4()),
                    "payload": {"assigned_to": rep_id},
                    "approval_status": "auto_approved",
                    "created_at": "2026-06-04T10:00:00Z",
                },
                {
                    "id": str(uuid4()),
                    "payload": {"recipient_id": rep_id},
                    "approval_status": "pending",
                    "created_at": "2026-06-04T11:00:00Z",
                },
            ],
            "ai_agent_approval_requests": [],
            "ai_agent_runs": [
                {
                    "id": str(uuid4()),
                    "entity_type": "user",
                    "entity_id": rep_id,
                    "started_at": "2026-06-04T08:00:00Z",
                }
            ],
        }
    )

    stats = asyncio.run(_build_team_agent_stats(db, {"id": manager_id, "role": "sales_manager"}))

    rep = next(row for row in stats["agents"] if row["agent_id"] == rep_id)
    assert rep["actions"] == 2
    assert rep["pending_actions"] == 1
    assert rep["daily_summaries"] == 1
