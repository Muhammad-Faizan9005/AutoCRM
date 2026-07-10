from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation
from app.schemas.task_deadline import TaskDeadlineAlertIn
from app.services.notification_service import NotificationService


DONE_TASK_STATES = {"done", "closed", "completed", "canceled", "cancelled"}
CUSTOMER_KEYWORDS = {
    "follow up",
    "proposal",
    "quote",
    "quotation",
    "contract",
    "demo",
    "meeting",
    "call",
    "invoice",
    "pricing",
    "send",
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class TaskDeadlineService:
    def __init__(self, db: Client):
        self.db = db
        self.notifications = NotificationService(db)

    async def list_candidates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return await run_db_operation(lambda: self._list_candidates_sync(limit=max(1, min(limit, 500))))

    async def process_due_alerts(self, *, limit: int = 100) -> dict[str, int]:
        candidates = await self.list_candidates(limit=limit)
        created = 0
        skipped = 0
        for candidate in candidates:
            result = await self.create_rule_alerts(candidate)
            created += result["created"]
            skipped += result["skipped"]
        return {"created": created, "skipped": skipped, "candidates": len(candidates)}

    async def create_rule_alerts(self, candidate: dict[str, Any]) -> dict[str, int]:
        recipients = self._recipients_for(candidate)
        created = 0
        skipped = 0
        for recipient_id, audience in recipients:
            alert_type = self._alert_type(candidate, audience)
            message = self._message_for(candidate, audience)
            payload = TaskDeadlineAlertIn(
                task_id=candidate["task_id"],
                alert_type=alert_type,
                severity=candidate["severity"],
                recipient_id=recipient_id,
                message=message,
                llm_cache_key=candidate.get("llm_cache_key"),
                metadata={
                    "audience": audience,
                    "deadline_state": candidate.get("deadline_state"),
                    "is_customer_facing": bool(candidate.get("is_customer_facing")),
                },
            )
            response = await self.record_alert(payload)
            if response["created"]:
                created += 1
                await self.notifications.create_notification(
                    recipient_id=str(recipient_id),
                    actor_id=None,
                    type=alert_type,
                    title=self._title_for(candidate, audience),
                    message=message,
                    entity_type="task",
                    entity_id=str(candidate["task_id"]),
                )
            else:
                skipped += 1
        return {"created": created, "skipped": skipped}

    async def record_alert(self, payload: TaskDeadlineAlertIn) -> dict[str, Any]:
        return await run_db_operation(lambda: self._record_alert_sync(payload))

    def _list_candidates_sync(self, *, limit: int) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT t.id AS task_id, t.title, t.description, t.status, t.priority, t.due_at,
                           t.updated_at, t.entity_type, t.entity_id, t.assigned_to,
                           assignee.full_name AS assignee_name, assignee.email AS assignee_email,
                           COALESCE(l.owner_id, d.owner_id) AS owner_id,
                           owner.full_name AS owner_name,
                           manager.id AS manager_id,
                           COALESCE(NULLIF(l.name, ''), NULLIF(l.company, ''), NULLIF(o.name, ''), NULLIF(c.full_name, ''), 'CRM record') AS entity_name,
                           COALESCE(d.value, 0) AS deal_value,
                           latest_context.latest_at AS latest_context_at
                    FROM tasks t
                    LEFT JOIN agents assignee ON assignee.id = t.assigned_to
                    LEFT JOIN leads l ON t.entity_type = 'lead' AND l.id = t.entity_id
                    LEFT JOIN deals d ON (t.entity_type = 'deal' AND d.id = t.entity_id) OR d.lead_id = l.id
                    LEFT JOIN organizations o ON o.id = COALESCE(d.organization_id, l.organization_id)
                    LEFT JOIN customers c ON t.entity_type = 'customer' AND c.id = t.entity_id
                    LEFT JOIN agents owner ON owner.id = COALESCE(l.owner_id, d.owner_id)
                    LEFT JOIN team_members tm ON tm.agent_id = t.assigned_to
                    LEFT JOIN teams team_scope ON team_scope.id = tm.team_id
                    LEFT JOIN agents manager ON manager.id = team_scope.manager_id
                    LEFT JOIN LATERAL (
                        SELECT MAX(src.at) AS latest_at
                        FROM (
                            SELECT n.updated_at AS at
                            FROM notes n
                            WHERE n.entity_type = t.entity_type AND n.entity_id = t.entity_id
                            UNION ALL
                            SELECT cs.updated_at AS at
                            FROM call_sessions cs
                            WHERE cs.lead_id = l.id
                        ) src
                    ) latest_context ON true
                    WHERE t.due_at IS NOT NULL
                      AND NOT (LOWER(COALESCE(t.status, '')) = ANY(:done_states))
                      AND t.due_at <= (:now + INTERVAL '24 hours')
                    ORDER BY t.due_at ASC
                    LIMIT :limit
                    """
                ),
                {"now": now, "done_states": list(DONE_TASK_STATES), "limit": limit},
            ).mappings().all()
            admins = [
                row["id"]
                for row in conn.execute(
                    text(
                        """
                        SELECT id
                        FROM agents
                        WHERE COALESCE(is_active, true) = true
                          AND LOWER(COALESCE(role, '')) = 'admin'
                        """
                    )
                ).mappings().all()
            ]

        output = []
        for row in rows:
            item = dict(row)
            item["admin_ids"] = admins
            output.append(self._classify(item, now))
        with self.db.engine.connect() as conn:
            self._attach_cached_llm_outputs(conn, output)
        return output

    def _record_alert_sync(self, payload: TaskDeadlineAlertIn) -> dict[str, Any]:
        dedupe_key = self._dedupe_key(payload)
        with self.db.engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM task_deadline_alerts WHERE dedupe_key = :dedupe_key LIMIT 1"),
                {"dedupe_key": dedupe_key},
            ).mappings().first()
            if existing:
                return {"id": existing["id"], "created": False, "dedupe_key": dedupe_key}

            row = conn.execute(
                text(
                    """
                    INSERT INTO task_deadline_alerts
                        (task_id, alert_type, severity, recipient_id, dedupe_key, llm_cache_key,
                         llm_output, fallback_used, metadata)
                    VALUES
                        (:task_id, :alert_type, :severity, :recipient_id, :dedupe_key, :llm_cache_key,
                         :llm_output, :fallback_used, CAST(:metadata AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "task_id": str(payload.task_id),
                    "alert_type": payload.alert_type,
                    "severity": payload.severity,
                    "recipient_id": str(payload.recipient_id) if payload.recipient_id else None,
                    "dedupe_key": dedupe_key,
                    "llm_cache_key": payload.llm_cache_key,
                    "llm_output": payload.llm_output,
                    "fallback_used": payload.fallback_used,
                    "metadata": __import__("json").dumps({**payload.metadata, "message": payload.message}),
                },
            ).mappings().first()
        return {"id": row["id"] if row else None, "created": True, "dedupe_key": dedupe_key}

    @staticmethod
    def _attach_cached_llm_outputs(conn, candidates: list[dict[str, Any]]) -> None:
        cache_keys = [item.get("llm_cache_key") for item in candidates if item.get("llm_cache_key")]
        if not cache_keys:
            return
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT ON (llm_cache_key) llm_cache_key, llm_output, fallback_used
                FROM task_deadline_alerts
                WHERE llm_cache_key = ANY(:cache_keys)
                  AND llm_output IS NOT NULL
                ORDER BY llm_cache_key, created_at DESC
                """
            ),
            {"cache_keys": cache_keys},
        ).mappings().all()
        cached = {str(row["llm_cache_key"]): row for row in rows}
        for item in candidates:
            row = cached.get(str(item.get("llm_cache_key")))
            if not row:
                continue
            item["fresh_llm_output"] = row.get("llm_output")
            item["fallback_used"] = bool(row.get("fallback_used"))

    def _classify(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        due_at = row["due_at"]
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        delta_hours = (due_at - now).total_seconds() / 3600
        overdue_hours = max(0.0, -delta_hours)
        priority = str(row.get("priority") or "medium").strip().lower()
        title_desc = f"{row.get('title') or ''} {row.get('description') or ''}".lower()
        is_customer_facing = (
            str(row.get("entity_type") or "").lower() in {"lead", "deal", "customer", "organization"}
            or any(keyword in title_desc for keyword in CUSTOMER_KEYWORDS)
            or priority in {"high", "urgent"}
            or float(row.get("deal_value") or 0) >= 10000
        )

        if overdue_hours >= 24:
            deadline_state = "critical_overdue"
        elif overdue_hours >= 6:
            deadline_state = "seriously_overdue"
        elif overdue_hours > 0:
            deadline_state = "overdue"
        elif delta_hours <= self._due_soon_window(priority):
            deadline_state = "due_soon"
        else:
            deadline_state = "upcoming"

        severity = "low"
        if deadline_state == "critical_overdue":
            severity = "critical"
        elif deadline_state == "seriously_overdue" or priority in {"high", "urgent"}:
            severity = "high" if is_customer_facing else "medium"
        elif deadline_state == "overdue" and (overdue_hours >= 2 or is_customer_facing):
            severity = "medium"
        elif deadline_state == "due_soon" and is_customer_facing:
            severity = "medium"

        context_hash = self._context_hash(row)
        llm_cache_key = f"task-deadline:{row['task_id']}:{severity}:{context_hash}"
        should_use_llm = SEVERITY_RANK.get(severity, 0) >= 2 and is_customer_facing
        return {
            **row,
            "due_at": due_at,
            "deadline_state": deadline_state,
            "severity": severity,
            "is_customer_facing": is_customer_facing,
            "should_use_llm": should_use_llm,
            "hours_until_due": round(delta_hours, 2) if delta_hours >= 0 else None,
            "hours_overdue": round(overdue_hours, 2) if overdue_hours > 0 else None,
            "context_hash": context_hash,
            "llm_cache_key": llm_cache_key,
        }

    def _recipients_for(self, candidate: dict[str, Any]) -> list[tuple[str, str]]:
        recipients: list[tuple[str, str]] = []
        assigned_to = str(candidate.get("assigned_to") or "")
        owner_id = str(candidate.get("owner_id") or "")
        manager_id = str(candidate.get("manager_id") or "")
        if assigned_to:
            recipients.append((assigned_to, "rep"))
        if owner_id and owner_id != assigned_to and candidate.get("deadline_state") != "due_soon":
            recipients.append((owner_id, "owner"))
        rank = SEVERITY_RANK.get(str(candidate.get("severity")), 0)
        if manager_id and rank >= 3:
            recipients.append((manager_id, "manager"))
        if rank >= 4:
            for admin_id in candidate.get("admin_ids") or []:
                admin_text = str(admin_id)
                if admin_text:
                    recipients.append((admin_text, "admin"))

        seen = set()
        unique = []
        for recipient_id, audience in recipients:
            if recipient_id in seen:
                continue
            seen.add(recipient_id)
            unique.append((recipient_id, audience))
        return unique

    @staticmethod
    def _due_soon_window(priority: str) -> int:
        if priority in {"urgent", "high"}:
            return 4
        if priority == "low":
            return 24
        return 12

    @staticmethod
    def _context_hash(row: dict[str, Any]) -> str:
        raw = "|".join(
            str(row.get(key) or "")
            for key in ("task_id", "severity", "due_at", "updated_at", "latest_context_at", "title", "status")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _dedupe_key(payload: TaskDeadlineAlertIn) -> str:
        window = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        raw = f"{payload.task_id}:{payload.alert_type}:{payload.severity}:{payload.recipient_id}:{window}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _alert_type(candidate: dict[str, Any], audience: str) -> str:
        state = str(candidate.get("deadline_state") or "")
        severity = str(candidate.get("severity") or "low")
        if severity == "critical":
            return "task_critical_overdue"
        if severity == "high":
            return "task_customer_risk" if candidate.get("is_customer_facing") else "task_escalated"
        if state == "due_soon":
            return "task_due_soon"
        return "task_overdue"

    @staticmethod
    def _title_for(candidate: dict[str, Any], audience: str) -> str:
        severity = str(candidate.get("severity") or "low").title()
        if audience in {"manager", "admin"}:
            return f"{severity} overdue task needs attention"
        if candidate.get("deadline_state") == "due_soon":
            return f"{severity} task due soon"
        return f"{severity} task overdue"

    @staticmethod
    def _message_for(candidate: dict[str, Any], audience: str) -> str:
        title = str(candidate.get("title") or "Untitled task")
        entity = str(candidate.get("entity_name") or "CRM record")
        assignee = str(candidate.get("assignee_name") or "the assigned owner")
        if candidate.get("deadline_state") == "due_soon":
            hours = candidate.get("hours_until_due")
            return f"Task \"{title}\" for {entity} is due in about {hours} hours. Please complete it or update the status."
        hours_overdue = candidate.get("hours_overdue") or 0
        if audience in {"manager", "admin"}:
            return f"Task \"{title}\" for {entity} is overdue by about {hours_overdue} hours and assigned to {assignee}."
        return f"Task \"{title}\" for {entity} is overdue by about {hours_overdue} hours. Please take action or update the status."
