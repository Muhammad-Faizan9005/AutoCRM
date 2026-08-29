"""A lead resolved from the session must carry the attendee the calendar needs.

The front desk booked nothing for weeks because `session_lead` returned only
{id, owner_id} on the session path, so `create_booking` saw an empty
attendee_email and refused before ever calling Cal.com.
"""
import asyncio

from app.routers import frontdesk_internal as fi


def _lead_row(sql: str, params: dict):
    assert "name" in sql and "email" in sql, "the lead lookup must select the attendee fields"
    return {"id": params["id"], "owner_id": "owner-1", "name": "Mary Jane", "email": "mary@example.com"}


def test_session_lead_carries_name_and_email(monkeypatch):
    async def fake_query(db, sql, params, many=False):
        return _lead_row(sql, params)

    monkeypatch.setattr(fi, "query", fake_query)
    session = {"contact_type": "lead", "contact_id": "lead-1", "lead_owner_id": "owner-1"}
    lead = asyncio.run(fi.session_lead(None, session, None))
    assert lead["email"] == "mary@example.com"
    assert lead["name"] == "Mary Jane"


def test_explicit_lead_id_also_carries_email(monkeypatch):
    async def fake_query(db, sql, params, many=False):
        return _lead_row(sql, params)

    monkeypatch.setattr(fi, "query", fake_query)
    lead = asyncio.run(fi.session_lead(None, {}, "lead-1"))
    assert lead["email"] == "mary@example.com"
