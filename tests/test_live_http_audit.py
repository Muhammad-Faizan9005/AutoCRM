from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("AUTOCRM_LIVE_TESTS") != "1",
    reason="Set AUTOCRM_LIVE_TESTS=1 to run live HTTP audit tests.",
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKENISH_RE = re.compile(r"(?i)(access_token|refresh_token|csrf_token|raw_token|token_hash|password)")


@dataclass
class AuditRecord:
    name: str
    method: str
    url: str
    expected: str
    status_code: int | None
    elapsed_ms: float
    passed: bool
    request_body: Any = None
    response_shape: Any = None
    response_preview: str = ""
    error: str = ""


def _base_url(env_name: str, default: str) -> str:
    return os.getenv(env_name, default).rstrip("/")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if TOKENISH_RE.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:5]]
    if isinstance(value, str):
        return EMAIL_RE.sub("<email>", value)
    return value


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in list(value.items())[:12]}
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": _shape(value[0]) if value else None}
    if value is None:
        return "null"
    return type(value).__name__


def _preview(response: httpx.Response | None) -> tuple[Any, str]:
    if response is None or not response.content:
        return None, ""
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "application/json" in content_type:
        try:
            data = response.json()
            return _shape(data), json.dumps(_redact(data), ensure_ascii=False)[:600]
        except ValueError:
            return "invalid_json", text[:600]
    return "text", EMAIL_RE.sub("<email>", text)[:600]


@pytest.fixture(scope="session")
def audit_records() -> list[AuditRecord]:
    records: list[AuditRecord] = []
    yield records

    report_dir = Path(os.getenv("AUTOCRM_AUDIT_REPORT_DIR") or tempfile.gettempdir()) / "autocrm_live_audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"live_http_audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(records),
            "passed": sum(1 for record in records if record.passed),
            "failed": sum(1 for record in records if not record.passed),
        },
        "records": [asdict(record) for record in records],
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAUTOCRM_LIVE_AUDIT_REPORT={report_path}")


@pytest.fixture(scope="session")
def backend_url() -> str:
    return _base_url("AUTOCRM_BACKEND_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def ai_service_url() -> str:
    return _base_url("AUTOCRM_AI_SERVICE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def public_client() -> httpx.Client:
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        yield client


@pytest.fixture(scope="session")
def admin_client(backend_url: str, audit_records: list[AuditRecord]) -> httpx.Client:
    email = os.getenv("AUTOCRM_TEST_EMAIL")
    password = os.getenv("AUTOCRM_TEST_PASSWORD")
    if not email or not password:
        pytest.skip("AUTOCRM_TEST_EMAIL and AUTOCRM_TEST_PASSWORD are required for live audit tests.")

    client = httpx.Client(timeout=30.0, follow_redirects=False)
    response = _request(
        client,
        audit_records,
        "admin login",
        "POST",
        f"{backend_url}/api/auth/login",
        expected_status={200},
        expected="Admin login returns a safe user payload and auth cookies.",
        json_body={"email": email, "password": password},
        safe_body={"email": "<redacted>", "password": "<redacted>"},
    )
    if response.status_code != 200:
        client.close()
        pytest.fail("Admin login failed; cannot run authenticated live audit tests.")
    yield client
    client.close()


def _request(
    client: httpx.Client,
    records: list[AuditRecord],
    name: str,
    method: str,
    url: str,
    *,
    expected_status: set[int],
    expected: str,
    json_body: Any = None,
    safe_body: Any = None,
    max_ms: int | None = None,
) -> httpx.Response:
    started = time.perf_counter()
    response: httpx.Response | None = None
    error = ""
    try:
        response = client.request(method, url, json=json_body)
    except Exception as exc:  # pragma: no cover - operational live test
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    shape, preview = _preview(response)
    status_code = response.status_code if response is not None else None
    passed = status_code in expected_status and not error and (max_ms is None or elapsed_ms <= max_ms)
    records.append(
        AuditRecord(
            name=name,
            method=method,
            url=url,
            expected=expected if max_ms is None else f"{expected} Max {max_ms}ms.",
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            passed=passed,
            request_body=safe_body if safe_body is not None else _redact(json_body),
            response_shape=shape,
            response_preview=preview,
            error=error,
        )
    )
    assert not error, error
    assert response is not None
    assert response.status_code in expected_status
    if max_ms is not None:
        assert elapsed_ms <= max_ms
    return response


@pytest.mark.parametrize(
    ("name", "method", "path", "expected_status", "expected"),
    [
        ("backend root", "GET", "/", {200}, "Public root responds."),
        ("backend health", "GET", "/health", {200}, "Public health responds."),
        ("backend openapi", "GET", "/openapi.json", {200}, "OpenAPI schema responds."),
    ],
)
def test_backend_public_endpoints(
    public_client: httpx.Client,
    backend_url: str,
    audit_records: list[AuditRecord],
    name: str,
    method: str,
    path: str,
    expected_status: set[int],
    expected: str,
) -> None:
    _request(public_client, audit_records, name, method, f"{backend_url}{path}", expected_status=expected_status, expected=expected, max_ms=10000)


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/users/",
        "/api/agent/control-center",
        "/api/agent/approvals",
        "/api/agent/service-credentials",
    ],
)
def test_backend_protected_endpoints_reject_anonymous(
    public_client: httpx.Client,
    backend_url: str,
    audit_records: list[AuditRecord],
    path: str,
) -> None:
    _request(
        public_client,
        audit_records,
        f"anonymous rejected {path}",
        "GET",
        f"{backend_url}{path}",
        expected_status={401, 403},
        expected="Protected endpoint rejects missing session.",
        max_ms=10000,
    )


def test_backend_invalid_login_rejected(public_client: httpx.Client, backend_url: str, audit_records: list[AuditRecord]) -> None:
    _request(
        public_client,
        audit_records,
        "invalid login rejected",
        "POST",
        f"{backend_url}/api/auth/login",
        expected_status={401},
        expected="Incorrect credentials are rejected.",
        json_body={"email": "audit@example.com", "password": "wrong-password"},
        safe_body={"email": "<redacted>", "password": "<redacted>"},
        max_ms=15000,
    )


@pytest.mark.parametrize(
    ("name", "path", "max_ms"),
    [
        ("auth me", "/api/auth/me", 10000),
        ("users list", "/api/users/", 15000),
        ("leads list", "/api/leads/?limit=5", 15000),
        ("deals list", "/api/deals/?limit=5", 15000),
        ("tasks list", "/api/tasks/?limit=5", 15000),
        ("organizations list", "/api/organizations/?limit=5", 15000),
        ("notifications list", "/api/notifications/?limit=5", 15000),
        ("admin overview", "/api/admin/overview", 20000),
        ("agent control center", "/api/agent/control-center", 15000),
        ("agent approvals", "/api/agent/approvals", 15000),
        ("agent runs", "/api/agent/runs", 20000),
        ("agent settings", "/api/agent/settings", 15000),
        ("agent team stats", "/api/agent/team-stats", 20000),
        ("ai agents", "/api/agent/ai-agents", 20000),
        ("ai service credentials", "/api/agent/service-credentials", 15000),
    ],
)
def test_backend_authenticated_read_endpoints(
    admin_client: httpx.Client,
    backend_url: str,
    audit_records: list[AuditRecord],
    name: str,
    path: str,
    max_ms: int,
) -> None:
    response = _request(
        admin_client,
        audit_records,
        name,
        "GET",
        f"{backend_url}{path}",
        expected_status={200},
        expected="Authenticated read endpoint responds successfully.",
        max_ms=max_ms,
    )
    if path == "/api/agent/service-credentials":
        body = json.dumps(response.json()).lower()
        assert "raw_token" not in body
        assert "token_hash" not in body


@pytest.mark.parametrize(
    ("name", "path", "body"),
    [
        ("register invalid payload", "/api/auth/register", {}),
        ("lead create without csrf", "/api/leads/", {}),
        ("task create without csrf", "/api/tasks/", {}),
    ],
)
def test_backend_mutations_reject_invalid_or_csrf_less_requests(
    admin_client: httpx.Client,
    backend_url: str,
    audit_records: list[AuditRecord],
    name: str,
    path: str,
    body: dict[str, Any],
) -> None:
    _request(
        admin_client,
        audit_records,
        name,
        "POST",
        f"{backend_url}{path}",
        expected_status={403, 422},
        expected="Mutation rejects invalid payload or missing CSRF token.",
        json_body=body,
        max_ms=10000,
    )


@pytest.mark.parametrize(
    ("name", "path", "expected_status"),
    [
        ("ai health", "/health", {200}),
        ("ai readiness", "/health/ready", {200, 503}),
        ("ai openapi", "/openapi.json", {200}),
        ("ai config anonymous rejected", "/health/config", {401, 403}),
        ("ai run anonymous rejected", "/agent/runs/not-a-uuid", {401, 403, 422}),
    ],
)
def test_ai_service_live_smoke_and_security(
    public_client: httpx.Client,
    ai_service_url: str,
    audit_records: list[AuditRecord],
    name: str,
    path: str,
    expected_status: set[int],
) -> None:
    _request(
        public_client,
        audit_records,
        name,
        "GET",
        f"{ai_service_url}{path}",
        expected_status=expected_status,
        expected="AI service endpoint returns expected status.",
        max_ms=10000,
    )
