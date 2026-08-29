"""Cal.com booking client (API v2).

The front desk records every appointment in the CRM; when Cal.com credentials
are configured the same appointment is also placed on the real calendar so the
visitor's confirmation is truthful.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CAL_API_BASE = "https://api.cal.com/v2"
CAL_API_VERSION = "2024-08-13"
CAL_SLOTS_API_VERSION = "2024-09-04"

def is_configured() -> bool:
    return bool(settings.CAL_API_KEY and settings.CAL_USERNAME and settings.CAL_EVENT_TYPE_SLUG)

def localize(starts_at: datetime, time_zone: str | None = None) -> datetime:
    """Attach the business (or requested) zone to a bare clock time.

    A visitor saying "11 am" means 11 am where the business is. Reading that as
    UTC is what booked 11:00Z = 4 PM Karachi.
    """
    if starts_at.tzinfo is not None:
        return starts_at
    try:
        return starts_at.replace(tzinfo=ZoneInfo(time_zone or business_timezone()))
    except Exception:
        return starts_at.replace(tzinfo=timezone.utc)

def _utc_start(starts_at: datetime, time_zone: str | None = None) -> str:
    """Cal.com wants the start in UTC ISO 8601 with a literal Z suffix."""
    starts_at = localize(starts_at, time_zone)
    return starts_at.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

def match_slot(starts_at: datetime, slots: list[str]) -> str | None:
    """The offered slot string naming the same instant as `starts_at`, if any.

    Booking back the exact string Cal.com just handed us is what makes a
    rejection near-impossible: we never guess a start it has not offered.
    """
    for slot in slots:
        try:
            if datetime.fromisoformat(slot.replace("Z", "+00:00")) == starts_at:
                return slot
        except ValueError:
            continue
    return None

def _reason(response: httpx.Response) -> str:
    """Cal.com's human-readable rejection message, for logs and staff-facing errors."""
    try:
        error = (response.json() or {}).get("error") or {}
        return str(error.get("message") or response.text)[:300]
    except Exception:
        return response.text[:300]

def business_timezone() -> str:
    """The zone the business books in; bare visitor clock times mean this zone."""
    return settings.CAL_TIMEZONE or "UTC"

async def available_slots(*, day: datetime, time_zone: str | None = None) -> list[str]:
    """Bookable start times on the business-local day containing `day`.

    Returned strings are exactly what Cal.com reported (ISO 8601 with offset),
    so a caller can hand one straight back to `create_booking` without doing
    any timezone arithmetic of its own. Returns [] when unconfigured or the
    lookup fails.
    """
    if not is_configured():
        return []
    zone = time_zone or business_timezone()
    try:
        local_day = day.astimezone(ZoneInfo(zone))
    except Exception:
        zone, local_day = "UTC", day.astimezone(timezone.utc)
    date = local_day.date().isoformat()
    try:
        async with httpx.AsyncClient(timeout=settings.CAL_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{CAL_API_BASE}/slots",
                params={"eventTypeSlug": settings.CAL_EVENT_TYPE_SLUG, "username": settings.CAL_USERNAME,
                        "start": date, "end": date, "timeZone": zone},
                headers={"Authorization": f"Bearer {settings.CAL_API_KEY}", "cal-api-version": CAL_SLOTS_API_VERSION},
            )
        if response.status_code >= 400:
            logger.warning("Cal.com slots lookup failed (%s): %s", response.status_code, _reason(response))
            return []
        data = (response.json() or {}).get("data") or {}
    except Exception as exc:
        logger.warning("Cal.com slots lookup failed: %s", exc)
        return []
    return [str(slot.get("start")) for slot in data.get(date, []) if slot.get("start")]

async def create_booking(
    *,
    starts_at: datetime,
    attendee_name: str,
    attendee_email: str,
    time_zone: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a Cal.com booking.

    Returns {"uid", "meeting_url"} on success, or {"error": "..."} when the
    booking could not be placed (unconfigured, rejected slot, API down).
    """
    if not is_configured():
        return {"error": "Cal.com is not configured"}
    if not attendee_email:
        return {"error": "An attendee email is required to book on Cal.com"}
    zone = time_zone or business_timezone()
    starts_at = localize(starts_at, zone)
    if starts_at < datetime.now(timezone.utc):
        # Cal.com rejects past slots; say so plainly instead of blaming the API.
        return {"error": f"The requested slot ({_utc_start(starts_at, zone)}) is in the past"}

    # Book the exact string Cal.com offered for this instant. It just told us
    # the slot is free, so the only remaining rejection is a genuine race.
    offered = await available_slots(day=starts_at, time_zone=zone)
    start = match_slot(starts_at, offered) or _utc_start(starts_at, zone)
    if offered and start not in offered:
        return {"error": "The requested time is not an available opening",
                "alternative_slots": offered[:6]}
    body = {
        "eventTypeSlug": settings.CAL_EVENT_TYPE_SLUG,
        "username": settings.CAL_USERNAME,
        "start": start,
        "attendee": {"name": attendee_name or attendee_email, "email": attendee_email,
                     "timeZone": zone},
    }
    if notes:
        body["bookingFieldsResponses"] = {"notes": notes[:500]}

    try:
        async with httpx.AsyncClient(timeout=settings.CAL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{CAL_API_BASE}/bookings",
                json=body,
                headers={
                    "Authorization": f"Bearer {settings.CAL_API_KEY}",
                    "cal-api-version": CAL_API_VERSION,
                    "Content-Type": "application/json",
                },
            )
        if response.status_code >= 400:
            # Cal.com returns the human-readable reason (slot taken, out of
            # bounds, unknown event type) in the body.
            logger.warning("Cal.com booking rejected (%s): %s", response.status_code, response.text[:500])
            return {"error": f"Cal.com rejected the booking ({response.status_code}): {_reason(response)}"}
        data = (response.json() or {}).get("data") or {}
    except Exception as exc:  # network / decode failures
        logger.warning("Cal.com booking failed: %s", exc)
        return {"error": "Cal.com could not be reached"}

    return {
        "uid": data.get("uid"),
        "meeting_url": data.get("meetingUrl") or (data.get("location") if str(data.get("location", "")).startswith("http") else None),
    }
