import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.main import app
from app.middleware.rate_limiter import reset_rate_limiter_state
from app.schemas.customer import CustomerCreate
from app.schemas.ticket import TicketCreate


def test_security_headers_and_request_id_are_present():
    reset_rate_limiter_state()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy")


def test_docs_route_uses_docs_compatible_csp():
    reset_rate_limiter_state()
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    csp = response.headers.get("Content-Security-Policy", "")
    assert "script-src" in csp
    assert "https://cdn.jsdelivr.net" in csp


def test_rate_limit_enforced(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 2)
    reset_rate_limiter_state()

    with TestClient(app) as client:
        first = client.get("/health")
        second = client.get("/health")
        third = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("Retry-After")


def test_request_size_limit_returns_413(monkeypatch):
    monkeypatch.setattr(settings, "MAX_REQUEST_SIZE_BYTES", 40)
    reset_rate_limiter_state()

    payload = {
        "email": "agent@example.com",
        "password": "x" * 500,
    }

    with TestClient(app) as client:
        response = client.post("/api/auth/login", json=payload)

    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Request body is too large"


def test_customer_schema_sanitizes_html_input():
    customer = CustomerCreate(
        email="customer@example.com",
        full_name="<b>Jane Doe</b>",
        phone="+1 555 123 4567",
        company="<i>Acme Corp</i>",
        notes="<div>Needs follow up</div>",
    )

    assert customer.full_name == "Jane Doe"
    assert customer.company == "Acme Corp"
    assert customer.notes == "Needs follow up"


def test_ticket_schema_blocks_dangerous_sql_tokens():
    try:
        TicketCreate(
            customer_id="11111111-1111-1111-1111-111111111111",
            subject="DROP TABLE tickets",
            description="normal",
            status="open",
            priority="medium",
            category="support",
        )
        assert False, "Expected validation to fail for dangerous SQL tokens"
    except ValidationError as exc:
        assert "blocked SQL tokens" in str(exc)
