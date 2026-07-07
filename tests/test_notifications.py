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
