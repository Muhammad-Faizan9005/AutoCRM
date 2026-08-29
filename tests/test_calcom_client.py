"""Self-check for the Cal.com booking client (no network required)."""
import asyncio
from datetime import datetime, timezone

from app.services import calcom

def test_utc_start_normalises_to_z_suffix():
    naive = datetime(2026, 9, 2, 14, 0, 0)
    assert calcom._utc_start(naive, "UTC") == "2026-09-02T14:00:00Z"

    aware = datetime(2026, 9, 2, 14, 0, 0, tzinfo=timezone.utc)
    assert calcom._utc_start(aware) == "2026-09-02T14:00:00Z"

def test_bare_clock_time_means_business_zone():
    """11 am asked for in Karachi must not be shipped as 11:00Z (= 4 PM there)."""
    assert calcom._utc_start(datetime(2026, 9, 3, 11, 0), "Asia/Karachi") == "2026-09-03T06:00:00Z"
    aware = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
    assert calcom.localize(aware, "Asia/Karachi") == aware  # an explicit offset is respected

def test_match_slot_finds_the_offered_string_for_the_instant():
    slots = ["2026-09-03T10:30:00.000+05:00", "2026-09-03T11:00:00.000+05:00", "bad"]
    assert calcom.match_slot(datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc), slots) == slots[1]
    assert calcom.match_slot(datetime(2026, 9, 3, 7, 15, tzinfo=timezone.utc), slots) is None

def test_create_booking_refuses_a_time_cal_never_offered(monkeypatch):
    """No HTTP call, no 409: an unoffered time is answered with real openings."""
    monkeypatch.setattr(calcom, "is_configured", lambda: True)
    slots = ["2026-09-03T11:00:00.000+05:00"]

    async def fake_slots(*, day, time_zone=None):
        return slots

    monkeypatch.setattr(calcom, "available_slots", fake_slots)
    result = asyncio.run(calcom.create_booking(
        starts_at=datetime(2026, 9, 3, 11, 15), attendee_name="Mary",
        attendee_email="m@example.com", time_zone="Asia/Karachi"))
    assert "not an available opening" in result["error"]
    assert result["alternative_slots"] == slots

def test_create_booking_requires_attendee_email(monkeypatch):
    monkeypatch.setattr(calcom, "is_configured", lambda: True)
    result = asyncio.run(calcom.create_booking(starts_at=datetime.now(timezone.utc), attendee_name="Jane", attendee_email=""))
    assert result["error"]

def test_create_booking_unconfigured_reports_error(monkeypatch):
    monkeypatch.setattr(calcom, "is_configured", lambda: False)
    result = asyncio.run(calcom.create_booking(starts_at=datetime.now(timezone.utc), attendee_name="Jane", attendee_email="jane@example.com"))
    assert result["error"]

def test_create_booking_rejects_past_slot(monkeypatch):
    monkeypatch.setattr(calcom, "is_configured", lambda: True)
    result = asyncio.run(calcom.create_booking(starts_at=datetime(2024, 8, 31, 15, 0, tzinfo=timezone.utc), attendee_name="Micheal", attendee_email="m@example.com"))
    assert "past" in result["error"]

def test_business_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(calcom.settings, "CAL_TIMEZONE", "")
    assert calcom.business_timezone() == "UTC"

def test_available_slots_unconfigured_is_empty(monkeypatch):
    monkeypatch.setattr(calcom, "is_configured", lambda: False)
    assert asyncio.run(calcom.available_slots(day=datetime.now(timezone.utc))) == []
