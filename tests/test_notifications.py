from __future__ import annotations

from uuid import uuid4

from app.repositories.notification_repository import _normalize_legacy_notification


def test_legacy_deal_risk_approval_notification_is_rendered_as_alert() -> None:
    row = {
        "id": str(uuid4()),
        "type": "agent_approval",
        "entity_type": "deal",
        "title": "AI approval required: Deal risk alert",
        "message": "Deal risk detected Review approval #abc123 in the AI Control Center.",
    }

    normalized = _normalize_legacy_notification(row)

    assert normalized["type"] == "agent_alert"
    assert normalized["title"] == "Deal risk alert"
    assert normalized["message"].startswith("Deal risk detected.")


def test_legacy_agent_approval_notification_hides_raw_approval_id() -> None:
    row = {
        "id": str(uuid4()),
        "type": "agent_approval",
        "entity_type": "lead",
        "title": "AI approval required: Follow up with lead",
        "message": "No recent activity Review approval #2152b9c3-e80b-40bd-a10e-c7076859 in the AI Control Center.",
    }

    normalized = _normalize_legacy_notification(row)

    assert normalized["title"] == "AI approval required: Follow up with lead"
    assert normalized["message"] == "No recent activity. Review in the AI Control Center."
    assert "#" not in normalized["message"]
