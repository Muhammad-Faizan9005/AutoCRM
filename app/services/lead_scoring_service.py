from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation


async def calculate_lead_score(db: Client, lead_id: str) -> dict[str, Any] | None:
    def _query():
        with db.engine.begin() as conn:
            lead = conn.execute(
                text("SELECT * FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            if not lead:
                return None

            tasks = conn.execute(
                text("SELECT status, due_at FROM tasks WHERE entity_type='lead' AND entity_id=:lead_id"),
                {"lead_id": lead_id},
            ).mappings().all()
            deals = conn.execute(
                text("SELECT status, value FROM deals WHERE lead_id=:lead_id"),
                {"lead_id": lead_id},
            ).mappings().all()
            calls = conn.execute(
                text("SELECT transcript, processing_status FROM call_sessions WHERE lead_id=:lead_id"),
                {"lead_id": lead_id},
            ).mappings().all()
            notes_count = conn.execute(
                text("SELECT COUNT(*) FROM notes WHERE entity_type='lead' AND entity_id=:lead_id"),
                {"lead_id": lead_id},
            ).scalar() or 0

            score = 35
            reasons: list[str] = []
            status_value = str(lead.get("status") or "").lower()
            if status_value in {"qualified", "proposal", "negotiation"}:
                score += 25
                reasons.append("lead is in a high-intent status")
            elif status_value in {"unqualified", "junk", "lost"}:
                score -= 35
                reasons.append("lead is marked low quality")

            if lead.get("email") and lead.get("phone"):
                score += 10
                reasons.append("complete contact information is available")
            elif lead.get("email") or lead.get("phone"):
                score += 5
                reasons.append("partial contact information is available")

            open_deals = [
                deal for deal in deals
                if str(deal.get("status") or "").lower() not in {"won", "lost", "closed_won", "closed_lost"}
            ]
            if open_deals:
                score += 20
                reasons.append(f"{len(open_deals)} open deal(s) are linked")
            if any(str(task.get("status") or "").lower() not in {"done", "canceled"} for task in tasks):
                score += 10
                reasons.append("there are active follow-up tasks")
            if any(call.get("transcript") for call in calls):
                score += 10
                reasons.append("meeting/call transcript is available")
            if notes_count:
                score += 5
                reasons.append("notes are captured for this lead")

            score = max(0, min(100, score))
            priority = "High" if score >= 75 else "Medium" if score >= 45 else "Low"
            reason = (
                f"{priority} priority because "
                + (", ".join(reasons[:4]) if reasons else "limited engagement data is available")
                + "."
            )
            conn.execute(
                text("UPDATE leads SET score=:score, score_reason=:reason, updated_at=NOW() WHERE id=:lead_id"),
                {"score": score, "reason": reason, "lead_id": lead_id},
            )
            return {"score": score, "priority": priority, "score_reason": reason}

    return await run_db_operation(_query)


async def calculate_lead_score_sweep(db: Client, limit: int = 100) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 100), 500))

    def _lead_ids():
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id
                    FROM leads
                    ORDER BY
                      CASE WHEN score IS NULL OR score_reason IS NULL THEN 0 ELSE 1 END,
                      updated_at ASC NULLS FIRST,
                      created_at ASC NULLS FIRST
                    LIMIT :limit;
                    """
                ),
                {"limit": safe_limit},
            ).mappings().all()
            return [str(row["id"]) for row in rows]

    lead_ids = await run_db_operation(_lead_ids)
    updated = 0
    missing = 0
    for lead_id in lead_ids:
        result = await calculate_lead_score(db, lead_id)
        if result is None:
            missing += 1
        else:
            updated += 1

    return {"updated": updated, "missing": missing, "limit": safe_limit}
