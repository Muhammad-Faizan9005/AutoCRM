from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import text
from supabase import Client

from app.config import settings
from app.database import run_db_operation

logger = logging.getLogger(__name__)

_sweep_state_lock = asyncio.Lock()
_sweep_running = False


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


async def calculate_lead_score_sweep(
    db: Client,
    limit: int = 100,
    *,
    concurrency: int | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 100), 500))
    safe_concurrency = max(1, min(int(concurrency or settings.LEAD_SCORE_SWEEP_CONCURRENCY), safe_limit))

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
    semaphore = asyncio.Semaphore(safe_concurrency)

    async def _score_one(lead_id: str) -> str:
        async with semaphore:
            try:
                result = await calculate_lead_score(db, lead_id)
            except Exception:
                logger.exception("lead_score_sweep_item_failed lead_id=%s", lead_id)
                return "error"
            return "missing" if result is None else "updated"

    outcomes = await asyncio.gather(*(_score_one(lead_id) for lead_id in lead_ids))
    updated = sum(1 for outcome in outcomes if outcome == "updated")
    missing = sum(1 for outcome in outcomes if outcome == "missing")
    errors = sum(1 for outcome in outcomes if outcome == "error")

    return {
        "updated": updated,
        "missing": missing,
        "errors": errors,
        "limit": safe_limit,
        "selected": len(lead_ids),
        "concurrency": safe_concurrency,
    }


async def queue_lead_score_sweep(
    background_tasks: BackgroundTasks,
    db: Client,
    limit: int = 100,
) -> dict[str, Any]:
    global _sweep_running

    safe_limit = max(1, min(int(limit or 100), 500))
    async with _sweep_state_lock:
        if _sweep_running:
            return {
                "status": "already_running",
                "accepted": False,
                "limit": safe_limit,
                "mode": "background",
            }
        _sweep_running = True

    background_tasks.add_task(_run_queued_lead_score_sweep, db, safe_limit)
    return {
        "status": "accepted",
        "accepted": True,
        "limit": safe_limit,
        "mode": "background",
    }


async def _run_queued_lead_score_sweep(db: Client, limit: int) -> None:
    global _sweep_running

    try:
        result = await calculate_lead_score_sweep(db, limit=limit)
        logger.info("lead_score_sweep_background_completed result=%s", result)
    except Exception:
        logger.exception("lead_score_sweep_background_failed")
    finally:
        async with _sweep_state_lock:
            _sweep_running = False
