from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_auth, require_ai_agent_auth, require_sales_manager_or_admin, generate_ai_service_token
from app.database import get_db, run_db_operation
from app.repositories.agent_control_repository import (
    AgentActionRepository,
    AgentApprovalRepository,
    AgentRunRepository,
    AgentSettingRepository,
    AgentTraceRepository,
    AiAgentCredentialRepository,
    AiAgentRepository,
)
from app.repositories.note_repository import NoteRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.agent_action import (
    AgentActionIn,
    AgentActionResponse,
    AgentApprovalDecision,
    AgentRunCreate,
    AgentRunResponse,
    AgentSettingResponse,
    AgentSettingUpdate,
    AgentTraceCreate,
    AiAgentCredentialCreate,
    AiAgentUpdate,
)
from app.schemas.note import NoteCreate
from app.schemas.task import TaskCreate
from app.services.notification_service import NotificationService

router = APIRouter()

RISKY_ACTIONS = {"create_alert", "send_email", "update_deal_stage", "update_lead_status"}
SUPPORTED_ACTIONS = {"create_task", "create_note", "create_alert"}

AI_AGENT_RUNTIME_ALIASES = {
    "action_manager_agent": {"action_manager_agent", "action_manager", "task_auto", "create_task"},
    "lead_assistant": {"lead_assistant", "stale_lead", "lead_nudge"},
    "deal_risk_watcher": {"deal_risk_watcher", "deal_risk"},
    "daily_summary_assistant": {"daily_summary_assistant", "daily_summary", "summary_assistant"},
    "meeting_agent": {"meeting_agent", "meeting_assistant", "meeting_complete", "meeting_intel"},
}
IMPLEMENTED_AI_AGENT_KEYS = set(AI_AGENT_RUNTIME_ALIASES.keys())


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)


def get_note_repository(db: Client = Depends(get_db)) -> NoteRepository:
    return NoteRepository(db)


def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_run_repository(db: Client = Depends(get_db)) -> AgentRunRepository:
    return AgentRunRepository(db)


def get_trace_repository(db: Client = Depends(get_db)) -> AgentTraceRepository:
    return AgentTraceRepository(db)


def get_action_repository(db: Client = Depends(get_db)) -> AgentActionRepository:
    return AgentActionRepository(db)


def get_approval_repository(db: Client = Depends(get_db)) -> AgentApprovalRepository:
    return AgentApprovalRepository(db)


def get_setting_repository(db: Client = Depends(get_db)) -> AgentSettingRepository:
    return AgentSettingRepository(db)


def get_ai_agent_repository(db=Depends(get_db)) -> AiAgentRepository:
    return AiAgentRepository(db)


def get_ai_agent_credential_repository(db=Depends(get_db)) -> AiAgentCredentialRepository:
    return AiAgentCredentialRepository(db)


@router.get("/settings", response_model=list[AgentSettingResponse])
async def list_agent_settings(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    return await _ensure_agent_settings(setting_repository)


@router.patch("/settings/{agent_type}", response_model=AgentSettingResponse)
async def update_agent_setting(
    agent_type: str,
    payload: AgentSettingUpdate,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    await _ensure_agent_settings(setting_repository)
    existing = await setting_repository.find_by_agent_type(agent_type)
    update_payload = {
        "enabled": payload.enabled,
        "updated_by": current_user.get("id"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing:
        return await setting_repository.update_by_id(existing["id"], update_payload)
    return await setting_repository.create({"agent_type": agent_type, **update_payload})


@router.get("/team-stats")
async def get_agent_team_stats(
    current_user: dict = Depends(require_sales_manager_or_admin()),
    db: Client = Depends(get_db),
):
    return await _build_team_agent_stats(db, current_user)


@router.post("/runs", response_model=AgentRunResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreate,
    _current_user: dict = Depends(require_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    if payload.external_run_id:
        existing = await run_repository.find_by_external_id(str(payload.external_run_id))
        if existing:
            return existing
    return await run_repository.create(payload.model_dump(mode="json"))


@router.get("/runs")
async def list_agent_runs(
    status_filter: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    _current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    filters = {
        "status": status_filter,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
    }
    current_runs = await run_repository.list(filters=filters, order_by="started_at", order_desc=True)
    legacy_runs = await _list_legacy_ai_runs(db, filters)
    legacy_interactions = await _list_legacy_ai_interactions(db, filters)
    return _sort_runs([*current_runs, *legacy_runs, *legacy_interactions])


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    _current_user: dict = Depends(require_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    return await run_repository.get_by_id(run_id)


@router.post("/runs/{run_id}/trace", status_code=status.HTTP_201_CREATED)
async def create_run_trace(
    run_id: UUID,
    payload: AgentTraceCreate,
    _current_user: dict = Depends(require_auth),
    trace_repository: AgentTraceRepository = Depends(get_trace_repository),
):
    return await trace_repository.create({"run_id": str(run_id), **payload.model_dump(mode="json")})


@router.get("/runs/{run_id}/trace")
async def get_run_trace(
    run_id: UUID,
    _current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    trace_repository: AgentTraceRepository = Depends(get_trace_repository),
):
    trace = await trace_repository.list_for_run(run_id)
    if trace:
        return trace
    legacy_trace = await _list_legacy_run_trace(db, run_id)
    if legacy_trace:
        return legacy_trace
    return await _legacy_interaction_as_trace(db, run_id)


@router.get("/memory/{entity_type}/{entity_id}")
async def get_entity_memory(
    entity_type: str,
    entity_id: UUID,
    _current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    action_repository: AgentActionRepository = Depends(get_action_repository),
):
    current_memory = await action_repository.list(
        filters={"entity_type": entity_type, "entity_id": str(entity_id)},
        order_by="created_at",
        order_desc=True,
        limit=25,
    )
    legacy_memory = await _list_legacy_ai_actions(db, entity_type, entity_id)
    return _sort_memory([*current_memory, *legacy_memory])[:25]


@router.get("/approvals")
async def list_pending_approvals(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
):
    return await approval_repository.list_pending()


@router.get("/control-center")
async def get_control_center_snapshot(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
):
    """Return the AI Control Center data in one request.

    The frontend used to fire multiple first-load requests at the same time.
    On a cold backend/database connection that made the first page visit prone
    to request timeouts. This snapshot endpoint reuses shared data and avoids
    duplicate round trips.
    """
    filters = {"status": None, "entity_type": None, "entity_id": None}

    current_runs = await run_repository.list(order_by="started_at", order_desc=True)
    legacy_runs = await _list_legacy_ai_runs(db, filters)
    legacy_interactions = await _list_legacy_ai_interactions(db, filters)
    runs = _sort_runs([*current_runs, *legacy_runs, *legacy_interactions])

    approvals = await approval_repository.list_pending()
    agents = await ai_agent_repo.list_all()
    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=1000)

    return {
        "runs": runs,
        "approvals": approvals,
        "ai_agents": _build_ai_agent_rows(agents, runs, actions),
    }


@router.post("/approvals/{approval_id}/approve")
async def approve_agent_action(
    approval_id: UUID,
    decision: AgentApprovalDecision | None = None,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
    task_repository: TaskRepository = Depends(get_task_repository),
    note_repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    approval = await approval_repository.get_by_id(approval_id)
    if approval.get("state") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is already decided")

    action = await action_repository.get_by_id(approval["action_id"])
    created = await _dispatch_stored_action(
        action,
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )
    await action_repository.mark_dispatched(
        action["id"],
        crm_record_type=created["record_type"],
        crm_record_id=created["id"],
    )
    await approval_repository.update_by_id(
        approval_id,
        {
            "state": "approved",
            "approver_id": current_user.get("id"),
            "approver_note": (decision.note if decision else None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "approved", "action_id": action["id"], "id": created["id"]}


@router.post("/approvals/{approval_id}/reject")
async def reject_agent_action(
    approval_id: UUID,
    decision: AgentApprovalDecision | None = None,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
):
    approval = await approval_repository.get_by_id(approval_id)
    if approval.get("state") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is already decided")

    await action_repository.update_by_id(
        approval["action_id"],
        {"approval_status": "rejected", "dispatch_status": "rejected"},
    )
    await approval_repository.update_by_id(
        approval_id,
        {
            "state": "rejected",
            "approver_id": current_user.get("id"),
            "approver_note": (decision.note if decision else None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "rejected", "action_id": approval["action_id"]}


@router.post("/actions", response_model=AgentActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def dispatch_agent_action(
    payload: AgentActionIn,
    current_user: dict = Depends(require_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    task_repository: TaskRepository = Depends(get_task_repository),
    note_repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    _validate_action_payload(payload)
    existing = await _find_existing_action(payload, action_repository)
    if existing:
        return AgentActionResponse(
            status="pending_approval" if existing.get("approval_status") == "pending" else "created",
            action_type=existing["action_type"],
            action_id=str(existing["id"]),
            id=str(existing.get("crm_record_id")) if existing.get("crm_record_id") else None,
        )

    run_id = await _resolve_run_id(payload, run_repository)
    needs_approval = _requires_approval(payload)
    action = await action_repository.create(
        {
            "run_id": run_id,
            "external_run_id": payload.run_id,
            "action_type": payload.action_type.strip().lower(),
            "entity_type": payload.entity_type,
            "entity_id": str(payload.entity_id),
            "reason": payload.reason,
            "payload": payload.data,
            "idempotency_key": payload.idempotency_key,
            "approval_status": "pending" if needs_approval else "auto_approved",
            "dispatch_status": "not_dispatched",
            "created_by": current_user.get("id"),
        }
    )

    if needs_approval:
        approval = await approval_repository.create(
            {
                "action_id": action["id"],
                "state": "pending",
                "requested_by": current_user.get("id"),
                "reason": payload.reason,
            }
        )
        return AgentActionResponse(
            status="pending_approval",
            action_type=payload.action_type,
            action_id=str(action["id"]),
            approval_id=str(approval["id"]),
        )

    created = await _dispatch_payload_action(
        payload,
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )
    await action_repository.mark_dispatched(
        action["id"],
        crm_record_type=created["record_type"],
        crm_record_id=created["id"],
    )
    return AgentActionResponse(
        status="created",
        action_type=payload.action_type,
        action_id=str(action["id"]),
        id=created["id"],
    )


async def _resolve_run_id(payload: AgentActionIn, run_repository: AgentRunRepository) -> str | None:
    if not payload.run_id:
        return None
    try:
        existing = await run_repository.find_by_external_id(payload.run_id)
    except Exception:
        existing = None
    if existing:
        return str(existing["id"])
    try:
        created = await run_repository.create(
            {
                "external_run_id": payload.run_id,
                "trigger_type": "agent_action_callback",
                "entity_id": str(payload.entity_id),
                "entity_type": payload.entity_type,
                "status": "running",
                "event_payload": {},
            }
        )
        return str(created["id"])
    except Exception:
        return None


async def _find_existing_action(
    payload: AgentActionIn,
    action_repository: AgentActionRepository,
) -> dict | None:
    if not payload.idempotency_key:
        return None
    return await action_repository.find_one(filters={"idempotency_key": payload.idempotency_key})


def _validate_action_payload(payload: AgentActionIn) -> None:
    action_type = payload.action_type.strip().lower()
    if action_type not in SUPPORTED_ACTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action_type")
    data = payload.data or {}
    if action_type == "create_task" and not data.get("title"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_task requires title")
    if action_type == "create_note" and not (data.get("content") or data.get("title")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_note requires content or title")
    if action_type == "create_alert" and not data.get("recipient_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_alert requires recipient_id")


def _requires_approval(payload: AgentActionIn) -> bool:
    action_type = payload.action_type.strip().lower()
    if payload.approval_status == "approved":
        return False
    if payload.requires_approval is True:
        return True
    return action_type in RISKY_ACTIONS


async def _dispatch_payload_action(
    payload: AgentActionIn,
    *,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
) -> dict[str, str | None]:
    return await _dispatch_action_data(
        action_type=payload.action_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        reason=payload.reason,
        data=payload.data,
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )


async def _dispatch_stored_action(
    action: dict,
    *,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
) -> dict[str, str | None]:
    return await _dispatch_action_data(
        action_type=action["action_type"],
        entity_type=action["entity_type"],
        entity_id=UUID(str(action["entity_id"])),
        reason=action["reason"],
        data=action["payload"] or {},
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )


async def _dispatch_action_data(
    *,
    action_type: str,
    entity_type: str,
    entity_id: UUID,
    reason: str,
    data: dict,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
) -> dict[str, str | None]:
    action_type = action_type.strip().lower()
    if action_type == "create_task":
        task_payload = TaskCreate(
            entity_type=entity_type,
            entity_id=entity_id,
            title=str(data.get("title")),
            description=data.get("description"),
            assigned_to=data.get("assigned_to"),
            status=data.get("status") or "backlog",
            priority=data.get("priority") or "medium",
            due_at=_parse_datetime(data.get("due_at")),
        )
        created = await task_repository.create(task_payload.model_dump())
        return {"record_type": "task", "id": str(created.get("id")) if created.get("id") else None}

    if action_type == "create_note":
        note_payload = NoteCreate(
            entity_type=entity_type,
            entity_id=entity_id,
            content=str(data.get("content") or data.get("title") or reason),
            author_id=UUID(str(current_user.get("id"))) if current_user.get("id") else None,
        )
        created = await note_repository.create(note_payload.model_dump())
        return {"record_type": "note", "id": str(created.get("id")) if created.get("id") else None}

    if action_type == "create_alert":
        created = await notification_service.create_notification(
            recipient_id=str(data.get("recipient_id")),
            actor_id=str(current_user.get("id") or ""),
            type="agent_alert",
            title=str(data.get("title") or "Agent alert"),
            message=str(data.get("message") or reason),
            entity_type=entity_type,
            entity_id=str(entity_id),
        )
        return {"record_type": "notification", "id": str(created.get("id")) if created else None}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action_type")


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _safe_table_select(
    db: Client,
    table_name: str,
    *,
    filters: dict[str, object] | None = None,
    order_by: str | None = None,
    order_desc: bool = False,
    limit: int | None = None,
) -> list[dict]:
    try:
        query = db.table(table_name).select("*")
        for column, value in (filters or {}).items():
            if value is not None:
                query = query.eq(column, value)
        if order_by:
            query = query.order(order_by, desc=order_desc)
        if limit:
            query = query.limit(limit)
        response = await run_db_operation(lambda: query.execute())
        return response.data or []
    except Exception:
        return []


async def _list_legacy_ai_runs(db: Client, filters: dict[str, object]) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_runs",
        filters={
            "status": filters.get("status"),
            "entity_type": filters.get("entity_type"),
            "entity_id": filters.get("entity_id"),
        },
        order_by="started_at",
        order_desc=True,
        limit=100,
    )
    return [
        {
            "id": row.get("id"),
            "external_run_id": row.get("id"),
            "trigger_type": row.get("trigger_type") or "legacy_ai_run",
            "entity_id": row.get("entity_id"),
            "entity_type": row.get("entity_type"),
            "status": row.get("status") or "unknown",
            "summary": row.get("summary"),
            "failure_cause": row.get("failure_cause"),
            "failure_detail": row.get("failure_detail"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "legacy_source": "ai_service.ai_runs",
        }
        for row in rows
    ]


async def _list_legacy_ai_interactions(db: Client, filters: dict[str, object]) -> list[dict]:
    if filters.get("status") or filters.get("entity_type") or filters.get("entity_id"):
        return []
    rows = await _safe_table_select(db, "ai_interactions", order_by="created_at", order_desc=True, limit=100)
    return [
        {
            "id": row.get("id"),
            "external_run_id": row.get("id"),
            "trigger_type": row.get("interaction_type") or "legacy_ai_interaction",
            "entity_id": row.get("ticket_id") or row.get("id"),
            "entity_type": "ticket" if row.get("ticket_id") else "ai_interaction",
            "status": "completed",
            "summary": _truncate(row.get("response") or row.get("prompt") or ""),
            "started_at": row.get("created_at"),
            "finished_at": row.get("created_at"),
            "legacy_source": "backend.ai_interactions",
        }
        for row in rows
    ]


async def _list_legacy_run_trace(db: Client, run_id: UUID) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_run_traces",
        filters={"run_id": str(run_id)},
        order_by="created_at",
        limit=100,
    )
    return [
        {
            "id": row.get("id"),
            "run_id": row.get("run_id"),
            "step": row.get("step"),
            "status": row.get("status") or "completed",
            "payload": row.get("payload") or {},
            "created_at": row.get("created_at"),
            "legacy_source": "ai_service.ai_run_traces",
        }
        for row in rows
    ]


async def _legacy_interaction_as_trace(db: Client, run_id: UUID) -> list[dict]:
    rows = await _safe_table_select(db, "ai_interactions", filters={"id": str(run_id)}, limit=1)
    if not rows:
        return []
    row = rows[0]
    return [
        {
            "id": f"{row.get('id')}:prompt",
            "run_id": row.get("id"),
            "step": "legacy_prompt_response",
            "status": "completed",
            "payload": {
                "interaction_type": row.get("interaction_type"),
                "prompt": row.get("prompt"),
                "response": row.get("response"),
                "model_used": row.get("model_used"),
                "tokens_used": row.get("tokens_used"),
            },
            "created_at": row.get("created_at"),
            "legacy_source": "backend.ai_interactions",
        }
    ]


async def _list_legacy_ai_actions(db: Client, entity_type: str, entity_id: UUID) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_actions",
        filters={"entity_type": entity_type, "entity_id": str(entity_id)},
        order_by="created_at",
        order_desc=True,
        limit=25,
    )
    return [
        {
            "id": row.get("id"),
            "run_id": row.get("run_id"),
            "action_type": row.get("action_type"),
            "entity_type": row.get("entity_type"),
            "entity_id": row.get("entity_id"),
            "reason": row.get("reason"),
            "payload": row.get("payload") or {},
            "approval_status": row.get("approval_status"),
            "dispatch_status": "legacy",
            "created_at": row.get("created_at"),
            "legacy_source": "ai_service.ai_actions",
        }
        for row in rows
    ]


def _sort_runs(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda item: str(item.get("started_at") or ""), reverse=True)


def _sort_memory(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _truncate(value: object, limit: int = 180) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."


async def _ensure_agent_settings(setting_repository: AgentSettingRepository) -> list[dict]:
    defaults = [
        ("lead_assistant", True),
        ("deal_risk_watcher", True),
        ("daily_summary_assistant", True),
    ]
    existing = await setting_repository.list_settings()
    by_type = {item.get("agent_type"): item for item in existing}
    for agent_type, enabled in defaults:
        if agent_type not in by_type:
            created = await setting_repository.create({"agent_type": agent_type, "enabled": enabled})
            by_type[agent_type] = created
    return sorted(by_type.values(), key=lambda item: str(item.get("agent_type") or ""))


async def _build_team_agent_stats(db: Client, current_user: dict) -> dict:
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()
    agents = await _safe_table_select(db, "agents", limit=500)
    team_members = await _safe_table_select(db, "team_members", limit=1000)
    teams = await _safe_table_select(db, "teams", limit=500)
    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=1000)
    approvals = await _safe_table_select(db, "ai_agent_approval_requests", order_by="created_at", order_desc=True, limit=1000)
    runs = await _safe_table_select(db, "ai_agent_runs", order_by="started_at", order_desc=True, limit=1000)

    manager_team_ids = {
        str(team.get("id"))
        for team in teams
        if str(team.get("manager_id")) == user_id
    }
    managed_agent_ids = {
        str(member.get("agent_id"))
        for member in team_members
        if str(member.get("team_id")) in manager_team_ids
    }
    if role == "admin":
        visible_agents = agents
    else:
        visible_agents = [agent for agent in agents if str(agent.get("id")) in managed_agent_ids or str(agent.get("id")) == user_id]

    reps = [agent for agent in visible_agents if str(agent.get("role") or "").lower() in {"sales_rep", "sales_manager", "manager"}]
    rep_rows = []
    for agent in reps:
        agent_id = str(agent.get("id"))
        agent_actions = [action for action in actions if _action_belongs_to_agent(action, agent_id)]
        agent_approvals = [approval for approval in approvals if str(approval.get("requested_by")) == agent_id or str(approval.get("approver_id")) == agent_id]
        agent_runs = [
            run
            for run in runs
            if str(run.get("entity_type")) == "user" and str(run.get("entity_id")) == agent_id
        ]
        rep_rows.append(
            {
                "agent_id": agent_id,
                "name": agent.get("full_name") or agent.get("email") or "Agent",
                "email": agent.get("email"),
                "role": agent.get("role"),
                "team_id": agent.get("team_id"),
                "actions": len(agent_actions),
                "pending_actions": sum(1 for action in agent_actions if action.get("approval_status") == "pending"),
                "approved_actions": sum(1 for action in agent_actions if action.get("approval_status") in {"approved", "auto_approved"}),
                "rejected_actions": sum(1 for action in agent_actions if action.get("approval_status") == "rejected"),
                "approval_decisions": len(agent_approvals),
                "daily_summaries": len(agent_runs),
                "last_activity_at": _latest_timestamp([*agent_actions, *agent_approvals, *agent_runs]),
            }
        )

    return {
        "scope": "admin" if role == "admin" else "manager",
        "teams": [
            team
            for team in teams
            if role == "admin" or str(team.get("id")) in manager_team_ids
        ],
        "agents": sorted(rep_rows, key=lambda item: str(item.get("last_activity_at") or ""), reverse=True),
        "totals": {
            "agents": len(rep_rows),
            "actions": sum(row["actions"] for row in rep_rows),
            "pending_actions": sum(row["pending_actions"] for row in rep_rows),
            "daily_summaries": sum(row["daily_summaries"] for row in rep_rows),
        },
    }


def _action_belongs_to_agent(action: dict, agent_id: str) -> bool:
    payload = action.get("payload") or {}
    return (
        str(action.get("created_by")) == agent_id
        or str(payload.get("assigned_to")) == agent_id
        or str(payload.get("recipient_id")) == agent_id
    )


def _latest_timestamp(rows: list[dict]) -> str | None:
    values = [
        str(row.get("created_at") or row.get("started_at") or row.get("decided_at") or "")
        for row in rows
    ]
    values = [value for value in values if value]
    return max(values) if values else None


def _build_ai_agent_rows(agents: list[dict], runs: list[dict], actions: list[dict]) -> list[dict]:
    result = []
    for agent in agents:
        agent_key = str(agent.get("agent_key") or "").lower()
        if agent_key not in IMPLEMENTED_AI_AGENT_KEYS:
            continue

        agent_type = str(agent.get("agent_type") or "").lower()
        aliases = {
            agent_key,
            agent_type,
            *AI_AGENT_RUNTIME_ALIASES.get(agent_key, set()),
        }
        aliases = {alias for alias in aliases if alias}

        agent_runs = [
            run for run in runs
            if str(run.get("trigger_type") or "").lower() in aliases
            or any(alias in str(run.get("summary") or "").lower() for alias in aliases)
        ]
        run_ids = {str(run.get("id")) for run in agent_runs if run.get("id")}
        agent_actions = [
            action for action in actions
            if str(action.get("run_id") or "") in run_ids
            or any(alias in str(action.get("reason") or "").lower() for alias in aliases)
            or any(alias in str(action.get("action_type") or "").lower() for alias in aliases)
        ]
        last_seen_at = agent.get("last_seen_at") or _latest_timestamp([*agent_runs, *agent_actions])
        result.append({
            **agent,
            "runtime_aliases": sorted(aliases),
            "is_wired": True,
            "total_runs": len(agent_runs),
            "total_actions": len(agent_actions),
            "pending_actions": sum(1 for action in agent_actions if action.get("approval_status") == "pending"),
            "last_seen_at": last_seen_at,
        })
    return result


# ===========================================================================
# AI Agents Registry Endpoints
# Human CRM users -> /api/agent/team-stats
# AI workers      -> /api/agent/ai-agents  (these endpoints)
# ===========================================================================

@router.get("/ai-agents")
async def list_ai_agents(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    db=Depends(get_db),
):
    """Return AI service-backed agents with run/action stats.

    The registry table may contain future placeholder identities. The control
    center should show the workers that are actually wired to the AI service so
    the page behaves like one application instead of a disconnected name list.
    """
    agents = await ai_agent_repo.list_all()

    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=2000)
    runs = await _safe_table_select(db, "ai_agent_runs", order_by="started_at", order_desc=True, limit=2000)

    return _build_ai_agent_rows(agents, runs, actions)


@router.patch("/ai-agents/{agent_key}")
async def update_ai_agent(
    agent_key: str,
    payload: AiAgentUpdate,
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    """Enable/disable or update metadata of a registered AI agent."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        return agent

    now = datetime.now(timezone.utc).isoformat()
    update_data["updated_at"] = now
    updated_agent = await ai_agent_repo.update_by_id(agent["id"], update_data)

    if "enabled" in update_data:
        enabled = bool(update_data["enabled"])
        normalized_agent_key = str(agent.get("agent_key") or agent_key or "").lower()
        setting_keys = {
            str(agent.get("agent_type") or ""),
            normalized_agent_key,
            *AI_AGENT_RUNTIME_ALIASES.get(normalized_agent_key, set()),
        }
        for setting_key in {key for key in setting_keys if key}:
            existing = await setting_repository.find_by_agent_type(setting_key)
            setting_payload = {
                "enabled": enabled,
                "updated_by": _current_user.get("id"),
                "updated_at": now,
            }
            if existing:
                await setting_repository.update_by_id(existing["id"], setting_payload)
            else:
                await setting_repository.create({"agent_type": setting_key, **setting_payload})

    return updated_agent


# ---------------------------------------------------------------------------
# AI Agent Credentials  (admin only — for AI service authentication)
# ---------------------------------------------------------------------------

@router.get("/ai-agents/{agent_key}/credentials")
async def list_ai_agent_credentials(
    agent_key: str,
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """List credentials (without raw tokens) for an AI agent."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")
    creds = await cred_repo.list_for_agent(str(agent["id"]))
    # Never expose token_hash in the response
    return [{k: v for k, v in c.items() if k != "token_hash"} for c in creds]


@router.post("/ai-agents/{agent_key}/credentials", status_code=status.HTTP_201_CREATED)
async def create_ai_agent_credential(
    agent_key: str,
    payload: AiAgentCredentialCreate,
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """
    Issue a new service token for the given AI agent.
    The raw_token is returned ONCE — store it securely; it cannot be retrieved again.
    """
    from datetime import timedelta

    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    raw_token, key_prefix, token_hash = generate_ai_service_token()

    expires_at = None
    if payload.expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)).isoformat()

    cred = await cred_repo.create({
        "ai_agent_id": str(agent["id"]),
        "key_prefix":  key_prefix,
        "token_hash":  token_hash,
        "scopes":      payload.scopes,
        "is_active":   True,
        "expires_at":  expires_at,
    })

    return {**{k: v for k, v in cred.items() if k != "token_hash"}, "raw_token": raw_token}


@router.delete("/ai-agents/{agent_key}/credentials/{credential_id}", status_code=status.HTTP_200_OK)
async def revoke_ai_agent_credential(
    agent_key: str,
    credential_id: UUID,
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """Revoke a service credential so it can no longer authenticate."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    await cred_repo.update_by_id(
        credential_id,
        {
            "is_active":  False,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "revoked", "credential_id": str(credential_id)}


# ---------------------------------------------------------------------------
# AI Service callback endpoint  (authenticated with AI agent credentials)
# ---------------------------------------------------------------------------

@router.post("/ai-service/heartbeat", status_code=status.HTTP_200_OK)
async def ai_service_heartbeat(
    ai_agent: dict = Depends(require_ai_agent_auth),
):
    """
    Heartbeat endpoint for AI services to confirm connectivity.
    Authenticated with X-AI-Agent-Key + X-AI-Service-Token headers.
    Updates last_seen_at automatically via the auth dependency.
    """
    return {
        "status": "ok",
        "agent_key":  ai_agent.get("agent_key"),
        "agent_type": ai_agent.get("agent_type"),
        "scopes":     ai_agent.get("credential_scopes"),
    }
