from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks

from app.services import lead_scoring_service


def test_queue_lead_score_sweep_rejects_overlap():
    async def _run():
        lead_scoring_service._sweep_running = False
        background_tasks = BackgroundTasks()

        first = await lead_scoring_service.queue_lead_score_sweep(background_tasks, db=object(), limit=100)
        second = await lead_scoring_service.queue_lead_score_sweep(background_tasks, db=object(), limit=100)

        lead_scoring_service._sweep_running = False
        return first, second, background_tasks

    first, second, background_tasks = asyncio.run(_run())

    assert first["status"] == "accepted"
    assert first["accepted"] is True
    assert first["mode"] == "background"
    assert second["status"] == "already_running"
    assert second["accepted"] is False
    assert len(background_tasks.tasks) == 1
