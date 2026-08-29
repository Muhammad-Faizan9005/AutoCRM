"""The handoff grace period decides what the visitor is told, and when they are emailed.

A rep who joins in time answers live, so emailing the visitor at handoff would
pre-empt them. Only once the window lapses does the promise of an email get made
-- and the email must actually be sent before the promise is spoken.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.routers import frontdesk as fd


def _session(**over):
    base = {"id": "s1", "contact_name": "Mary", "contact_email": "mary@example.com",
            "handoff_wait_until": None, "handoff_notified_at": None}
    base.update(over)
    return base


class _Mailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send_email(self, **kwargs):
        if self.fail:
            raise RuntimeError("Mailjet is down")
        self.sent.append(kwargs)


def _run(session, mailer, monkeypatch):
    async def fake_query(db, sql, params=None, many=False):
        return None

    monkeypatch.setattr(fd, "query", fake_query)
    return asyncio.run(fd._handoff_wait_reply(None, mailer, session))


def test_wait_elapsed_only_after_the_window():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert fd._wait_elapsed(_session(handoff_wait_until=future)) is False
    assert fd._wait_elapsed(_session(handoff_wait_until=past)) is True
    assert fd._wait_elapsed(_session()) is False  # no handoff, no window
    # A naive timestamp from the driver must not be read as local time.
    assert fd._wait_elapsed(_session(handoff_wait_until=past.replace(tzinfo=None))) is True


def test_inside_the_window_holds_the_visitor_and_sends_nothing(monkeypatch):
    mailer = _Mailer()
    reply = _run(_session(handoff_wait_until=datetime.now(timezone.utc) + timedelta(minutes=5)), mailer, monkeypatch)
    assert mailer.sent == []
    assert "email" not in reply.lower()


def test_lapsed_window_emails_once_then_promises_it(monkeypatch):
    mailer = _Mailer()
    reply = _run(_session(handoff_wait_until=datetime.now(timezone.utc) - timedelta(minutes=1)), mailer, monkeypatch)
    assert len(mailer.sent) == 1
    assert mailer.sent[0]["recipient_email"] == "mary@example.com"
    assert mailer.sent[0]["recipient_id"] is None  # a visitor is not a CRM user
    assert "mary@example.com" in reply

    # Already notified: the promise is repeated, the email is not.
    already = _session(handoff_wait_until=datetime.now(timezone.utc) - timedelta(minutes=1),
                       handoff_notified_at=datetime.now(timezone.utc))
    _run(already, mailer, monkeypatch)
    assert len(mailer.sent) == 1


def test_a_failed_send_never_promises_an_email(monkeypatch):
    reply = _run(_session(handoff_wait_until=datetime.now(timezone.utc) - timedelta(minutes=1)), _Mailer(fail=True), monkeypatch)
    assert "You'll get an email" not in reply
    assert "follow up" in reply


def test_no_email_address_asks_for_one_instead(monkeypatch):
    mailer = _Mailer()
    reply = _run(_session(contact_email=None, handoff_wait_until=datetime.now(timezone.utc) - timedelta(minutes=1)), mailer, monkeypatch)
    assert mailer.sent == []
    assert "email address" in reply
