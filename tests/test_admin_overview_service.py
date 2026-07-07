import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.admin_overview_service import AdminOverviewService


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, *, scalar_value: Any = None, rows: list[dict[str, Any]] | None = None):
        self.scalar_value = scalar_value
        self.rows = rows or []

    def scalar(self):
        return self.scalar_value

    def mappings(self):
        return FakeMappings(self.rows)


class FakeConnection:
    def __init__(self):
        self.seen_params: list[dict[str, Any]] = []
        self.now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)

    def execute(self, statement, params: dict[str, Any] | None = None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.seen_params.append(params)

        if "information_schema.columns" in sql:
            return FakeResult(rows=[
                {"column_name": "id"},
                {"column_name": "stage"},
                {"column_name": "status"},
                {"column_name": "value"},
                {"column_name": "closed_at"},
            ])

        if "open_deals" in sql:
            return FakeResult(rows=[{
                "open_deals": 2,
                "won_deals": 1,
                "won_30d": 1,
                "open_value": 75000,
                "won_value_30d": 25000,
            }])

        if "COUNT(*) AS total" in sql and "FROM leads l" in sql:
            return FakeResult(rows=[{"total": 12, "new_30d": 5, "unassigned": 2}])

        if "COUNT(*) AS total" in sql and "FROM tasks t" in sql:
            return FakeResult(rows=[{"total": 9, "overdue": 3, "unassigned": 1}])

        if "GROUP BY COALESCE(NULLIF(d.stage" in sql:
            return FakeResult(rows=[
                {"label": "proposal_quotation", "count": 4, "value": 60000},
                {"label": "negotiation", "count": 2, "value": 15000},
            ])

        if "GROUP BY COALESCE(NULLIF(l.source" in sql:
            return FakeResult(rows=[
                {"label": "website", "count": 6},
                {"label": "import", "count": 3},
            ])

        if "SELECT a.full_name AS label" in sql:
            return FakeResult(rows=[
                {"label": "Ava Rep", "leads": 8, "deals": 3, "pipeline": 52000},
                {"label": "Noah Rep", "leads": 4, "deals": 1, "pipeline": 23000},
            ])

        if "FROM ( SELECT 'New lead:" in sql:
            return FakeResult(rows=[
                {"message": "New lead: Acme", "at": self.now},
                {"message": "Deal updated: proposal_quotation", "at": self.now},
            ])

        if "MAX(a.updated_at)" in sql:
            return FakeResult(rows=[{"updated_at": self.now}])

        if "d.owner_id IS NULL" in sql:
            return FakeResult(scalar_value=1)

        if "d.updated_at < :since_30d" in sql:
            return FakeResult(scalar_value=2)

        if "FROM tickets" in sql:
            return FakeResult(scalar_value=4)

        if "LOWER(COALESCE(l.source" in sql:
            return FakeResult(scalar_value=3)

        if "a.status = 'invited'" in sql:
            return FakeResult(scalar_value=1)

        if "a.updated_at < :since_30d" in sql:
            return FakeResult(scalar_value=1)

        if "a.is_active = true" in sql:
            return FakeResult(scalar_value=2)

        if "SELECT COUNT(*) FROM agents a WHERE 1=1" in sql:
            return FakeResult(scalar_value=3)

        raise AssertionError(f"Unhandled SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeEngine:
    def __init__(self):
        self.connection = FakeConnection()

    def connect(self):
        return self.connection


class FakeDB:
    def __init__(self):
        self.engine = FakeEngine()


def test_admin_overview_uses_real_crm_metrics_and_manager_scope():
    db = FakeDB()
    service = AdminOverviewService(db)

    overview = service._get_overview_sync({
        "id": "manager-1",
        "role": "sales_manager",
    })

    assert overview["highlights"] == [
        {"label": "Open Pipeline", "value": "$75.0K", "meta": "2 open deals"},
        {"label": "Won Revenue", "value": "$25.0K", "meta": "1 won in 30 days"},
        {"label": "New Leads", "value": 5, "meta": "Last 30 days"},
        {"label": "Overdue Tasks", "value": 3, "meta": "9 total tasks"},
        {"label": "Active Operators", "value": 2, "meta": "1 inactive"},
        {"label": "Unassigned Records", "value": 4, "meta": "Leads, deals, and tasks"},
    ]
    assert overview["coverage"][0] == {
        "label": "Proposal Quotation",
        "percent": 100,
        "value": "4",
        "meta": "$60.0K",
    }
    assert overview["sources"][0] == {
        "label": "Website",
        "percent": 100,
        "value": "6",
        "meta": "leads",
    }
    assert overview["watchlist"][0]["title"] == "Stale open deals"
    assert overview["queues"][2] == {
        "title": "Support queue",
        "status": "4 open tickets",
        "age": "Live CRM data",
    }
    assert overview["team_performance"][0] == {
        "label": "Ava Rep",
        "value": "$52.0K",
        "meta": "3 deals / 8 leads",
    }
    assert overview["activity"][0]["message"] == "New lead: Acme"
    assert any(params.get("scope_user_id") == "manager-1" for params in db.engine.connection.seen_params)
