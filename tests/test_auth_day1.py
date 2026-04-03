import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import get_db
from app.main import app


class FakeResponse:
    def __init__(self, data: Any):
        self.data = data


class FakeTable:
    def __init__(self, table_name: str, db: "FakeDB"):
        self.table_name = table_name
        self.db = db
        self._filters: list[tuple[str, Any]] = []
        self._single = False
        self._insert_payload: dict[str, Any] | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, _value: int):
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._insert_payload is not None:
            row = self._insert_payload.copy()
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            row.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            self.db.tables[self.table_name].append(row)
            return FakeResponse([row.copy()])

        rows = self.db.tables[self.table_name]
        filtered = [
            row
            for row in rows
            if all(str(row.get(col)) == str(val) for col, val in self._filters)
        ]

        if self._single:
            return FakeResponse(filtered[0] if filtered else None)

        return FakeResponse(filtered)

    def insert(self, payload: dict[str, Any]):
        self._insert_payload = payload
        return self


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {
            "agents": [],
        }

    def table(self, table_name: str) -> FakeTable:
        return FakeTable(table_name, self)


def _client_with_fake_db() -> TestClient:
    fake_db = FakeDB()
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def test_day1_auth_flow_with_logout_invalidation(monkeypatch):
    monkeypatch.setattr("app.routers.auth.hash_password", lambda password: f"hashed::{password}")
    monkeypatch.setattr(
        "app.routers.auth.verify_password",
        lambda plain_password, hashed_password: hashed_password == f"hashed::{plain_password}",
    )

    client = _client_with_fake_db()

    register_payload = {
        "email": "agent@example.com",
        "password": "secure-pass-123",
        "full_name": "Test Agent",
        "role": "sales_rep",
    }

    register_res = client.post("/api/auth/register", json=register_payload)
    assert register_res.status_code == 201

    login_payload = {
        "email": "agent@example.com",
        "password": "secure-pass-123",
    }
    login_res = client.post("/api/auth/login", json=login_payload)
    assert login_res.status_code == 200
    tokens = login_res.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "agent@example.com"

    invalid_me = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert invalid_me.status_code == 401

    refresh_res = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 200

    logout_res = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 200

    me_after_logout = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_after_logout.status_code == 401

    refresh_after_logout = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_after_logout.status_code == 401


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
