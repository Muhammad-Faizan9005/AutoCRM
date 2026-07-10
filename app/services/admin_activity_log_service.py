from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from app.database import run_db_operation
from app.postgres_client import PostgresClient
from app.services.admin_overview_service import AdminOverviewService


_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_APPROVAL_REVIEW_RE = re.compile(
    r"\s*Review approval #[0-9a-fA-F-]+ in the AI Control Center\.?",
    re.IGNORECASE,
)


def _clean_activity_message(message: Any) -> str:
    text_value = str(message or "").strip()
    if not text_value:
        return "Activity recorded"

    cleaned = _APPROVAL_REVIEW_RE.sub("", text_value).strip()
    if cleaned != text_value:
        cleaned = f"{cleaned.rstrip('. ')}. Review in the AI Control Center."

    return _UUID_RE.sub("record", cleaned)


class AdminActivityLogService(AdminOverviewService):
    def __init__(self, db: PostgresClient):
        super().__init__(db)

    def _get_activity_log_sync(
        self,
        current_user: dict[str, Any],
        *,
        skip: int = 0,
        limit: int = 50,
        entity_type: str | None = None,
        event_type: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(current_user)
        params: dict[str, Any] = {
            **self._scope_params(scope),
            "scope_user_id": scope["user_id"],
            "offset": max(0, skip),
            "limit": max(1, min(limit, 200)),
        }
        filters: list[str] = []
        if entity_type:
            filters.append("entity_type = :entity_type")
            params["entity_type"] = entity_type.strip().lower()
        if event_type:
            filters.append("event_type = :event_type")
            params["event_type"] = event_type.strip().lower()
        if search:
            filters.append("(message ILIKE :search OR actor_name ILIKE :search OR actor_email ILIKE :search)")
            params["search"] = f"%{search.strip()}%"

        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.db.engine.connect() as conn:
            lead_scope = self._lead_scope_clause(scope, "l")
            deal_scope = self._deal_scope_clause(scope, "d", "l")
            task_scope = self._task_scope_clause(scope, "t")

            union_sql = f"""
                SELECT 'status-' || scl.id::text AS id,
                       'status_change' AS event_type,
                       scl.entity_type AS entity_type,
                       scl.entity_id AS entity_id,
                       'Status changed from ' || COALESCE(NULLIF(scl.old_status, ''), 'none') || ' to ' || scl.new_status AS message,
                       scl.changed_by AS actor_id,
                       a.full_name AS actor_name,
                       a.email AS actor_email,
                       scl.created_at AS happened_at
                FROM status_change_logs scl
                LEFT JOIN agents a ON a.id = scl.changed_by
                LEFT JOIN leads l ON scl.entity_type = 'lead' AND l.id = scl.entity_id
                LEFT JOIN deals d ON scl.entity_type = 'deal' AND d.id = scl.entity_id
                LEFT JOIN tasks t ON scl.entity_type = 'task' AND t.id = scl.entity_id
                WHERE (
                    :is_admin = true
                    OR (:is_manager = true AND (
                        (scl.entity_type = 'lead' AND EXISTS (
                            SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id
                            WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = l.owner_id
                        ))
                        OR (scl.entity_type = 'deal' AND EXISTS (
                            SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id
                            WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = COALESCE(d.owner_id, l.owner_id)
                        ))
                        OR (scl.entity_type = 'task' AND EXISTS (
                            SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id
                            WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = t.assigned_to
                        ))
                    ))
                    OR (:is_manager = false AND (
                        (scl.entity_type = 'lead' AND l.owner_id = :scope_user_id)
                        OR (scl.entity_type = 'deal' AND COALESCE(d.owner_id, l.owner_id) = :scope_user_id)
                        OR (scl.entity_type = 'task' AND t.assigned_to = :scope_user_id)
                    ))
                )

                UNION ALL
                SELECT 'lead-created-' || l.id::text,
                       'created',
                       'lead',
                       l.id,
                       'Lead created: ' || COALESCE(NULLIF(l.name, ''), NULLIF(l.email, ''), 'Lead'),
                       l.owner_id,
                       a.full_name,
                       a.email,
                       l.created_at
                FROM leads l
                LEFT JOIN agents a ON a.id = l.owner_id
                WHERE 1=1 {lead_scope}

                UNION ALL
                SELECT 'deal-updated-' || d.id::text,
                       'updated',
                       'deal',
                       d.id,
                       'Deal updated: ' || COALESCE(NULLIF(o.name, ''), NULLIF(l.company, ''), NULLIF(l.name, ''), NULLIF(d.stage, ''), 'Deal'),
                       COALESCE(d.owner_id, l.owner_id),
                       a.full_name,
                       a.email,
                       d.updated_at
                FROM deals d
                LEFT JOIN leads l ON l.id = d.lead_id
                LEFT JOIN organizations o ON o.id = d.organization_id
                LEFT JOIN agents a ON a.id = COALESCE(d.owner_id, l.owner_id)
                WHERE 1=1 {deal_scope}

                UNION ALL
                SELECT 'task-updated-' || t.id::text,
                       'updated',
                       'task',
                       t.id,
                       'Task updated: ' || COALESCE(NULLIF(t.title, ''), 'Task'),
                       t.assigned_to,
                       a.full_name,
                       a.email,
                       t.updated_at
                FROM tasks t
                LEFT JOIN agents a ON a.id = t.assigned_to
                WHERE 1=1 {task_scope}

                UNION ALL
                SELECT 'note-created-' || n.id::text,
                       'created',
                       COALESCE(NULLIF(n.entity_type, ''), 'note'),
                       n.entity_id,
                       'Note added',
                       n.author_id,
                       a.full_name,
                       a.email,
                       n.created_at
                FROM notes n
                LEFT JOIN agents a ON a.id = n.author_id
                WHERE (
                    :is_admin = true
                    OR n.author_id = :scope_user_id
                    OR (:is_manager = true AND EXISTS (
                        SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id
                        WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = n.author_id
                    ))
                )

                UNION ALL
                SELECT 'call-' || c.id::text,
                       COALESCE(NULLIF(c.status, ''), 'call'),
                       'call',
                       c.id,
                       'Call ' || COALESCE(NULLIF(c.status, ''), 'recorded'),
                       c.initiated_by,
                       a.full_name,
                       a.email,
                       COALESCE(c.started_at, c.created_at)
                FROM call_sessions c
                LEFT JOIN agents a ON a.id = c.initiated_by
                LEFT JOIN leads l ON l.id = c.lead_id
                WHERE 1=1 {lead_scope}

                UNION ALL
                SELECT 'notification-' || n.id::text,
                       n.type,
                       COALESCE(NULLIF(n.entity_type, ''), 'notification'),
                       n.entity_id,
                       n.title || ': ' || n.message,
                       n.actor_id,
                       a.full_name,
                       a.email,
                       n.created_at
                FROM notifications n
                LEFT JOIN agents a ON a.id = n.actor_id
                WHERE (
                    :is_admin = true
                    OR n.recipient_id = :scope_user_id
                    OR n.actor_id = :scope_user_id
                    OR (:is_manager = true AND EXISTS (
                        SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id
                        WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = n.recipient_id
                    ))
                )
            """
            scoped_params = {
                **params,
                "is_admin": scope["role"] == "admin",
                "is_manager": scope["role"] == "sales_manager",
            }

            rows = conn.execute(
                text(
                    f"""
                    WITH events AS ({union_sql})
                    SELECT *
                    FROM events
                    {where}
                    ORDER BY happened_at DESC NULLS LAST
                    OFFSET :offset LIMIT :limit
                    """
                ),
                scoped_params,
            ).mappings().all()
            total = conn.execute(
                text(f"WITH events AS ({union_sql}) SELECT COUNT(*) FROM events {where}"),
                scoped_params,
            ).scalar()

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["message"] = _clean_activity_message(item.get("message"))
            items.append(item)

        return {"items": items, "total": int(total or 0)}

    async def get_activity_log(
        self,
        current_user: dict[str, Any],
        *,
        skip: int = 0,
        limit: int = 50,
        entity_type: str | None = None,
        event_type: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        return await run_db_operation(
            lambda: self._get_activity_log_sync(
                current_user,
                skip=skip,
                limit=limit,
                entity_type=entity_type,
                event_type=event_type,
                search=search,
            )
        )
