from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import MetaData, Table, and_, create_engine, delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert


@dataclass
class QueryResult:
    data: Any


class PostgresQueryBuilder:
    def __init__(self, engine: Engine, table_name: str):
        self.engine = engine
        self.table_name = table_name

        self._operation = "select"
        self._select_columns: list[str] | None = None
        self._filters: list[tuple[str, str, Any]] = []
        self._order_by: tuple[str, bool] | None = None
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None
        self._single = False
        self._payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self._on_conflict: str | None = None

    def select(self, columns: str = "*") -> PostgresQueryBuilder:
        self._operation = "select"
        cleaned = [part.strip() for part in columns.split(",") if part.strip()]
        self._select_columns = None if not cleaned or cleaned == ["*"] else cleaned
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> PostgresQueryBuilder:
        self._operation = "insert"
        self._payload = payload
        return self

    def upsert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        on_conflict: str,
    ) -> PostgresQueryBuilder:
        self._operation = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> PostgresQueryBuilder:
        self._operation = "update"
        self._payload = payload
        return self

    def delete(self) -> PostgresQueryBuilder:
        self._operation = "delete"
        return self

    def eq(self, column: str, value: Any) -> PostgresQueryBuilder:
        self._filters.append(("eq", column, value))
        return self

    def lt(self, column: str, value: Any) -> PostgresQueryBuilder:
        self._filters.append(("lt", column, value))
        return self

    def order(self, column: str, desc: bool = False) -> PostgresQueryBuilder:
        self._order_by = (column, desc)
        return self

    def range(self, start: int, end: int) -> PostgresQueryBuilder:
        self._range = (start, end)
        return self

    def limit(self, value: int) -> PostgresQueryBuilder:
        self._limit = value
        return self

    def single(self) -> PostgresQueryBuilder:
        self._single = True
        self._limit = 1
        return self

    def execute(self) -> QueryResult:
        metadata = MetaData()
        table = Table(self.table_name, metadata, autoload_with=self.engine)

        if self._operation == "select":
            return QueryResult(self._execute_select(table))
        if self._operation == "insert":
            return QueryResult(self._execute_insert(table))
        if self._operation == "upsert":
            return QueryResult(self._execute_upsert(table))
        if self._operation == "update":
            return QueryResult(self._execute_update(table))
        if self._operation == "delete":
            return QueryResult(self._execute_delete(table))

        raise ValueError(f"Unsupported operation: {self._operation}")

    def _build_where_clause(self, table: Table):
        conditions = []
        for op, column, value in self._filters:
            if op == "eq":
                conditions.append(table.c[column] == value)
            elif op == "lt":
                conditions.append(table.c[column] < value)

        return and_(*conditions) if conditions else None

    def _execute_select(self, table: Table) -> list[dict[str, Any]] | dict[str, Any] | None:
        columns = [table.c[name] for name in self._select_columns] if self._select_columns else [table]
        stmt = select(*columns)

        where_clause = self._build_where_clause(table)
        if where_clause is not None:
            stmt = stmt.where(where_clause)

        if self._order_by:
            column_name, is_desc = self._order_by
            ordering = table.c[column_name].desc() if is_desc else table.c[column_name].asc()
            stmt = stmt.order_by(ordering)

        if self._range is not None:
            start, end = self._range
            stmt = stmt.offset(start).limit((end - start) + 1)

        if self._limit is not None:
            stmt = stmt.limit(self._limit)

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            serialized = [dict(row) for row in rows]

        if self._single:
            return serialized[0] if serialized else None

        return serialized

    def _execute_insert(self, table: Table) -> list[dict[str, Any]]:
        if self._payload is None:
            raise ValueError("insert payload is required")

        stmt = pg_insert(table).values(self._payload).returning(table)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def _execute_upsert(self, table: Table) -> list[dict[str, Any]]:
        if self._payload is None:
            raise ValueError("upsert payload is required")
        if not self._on_conflict:
            raise ValueError("upsert requires on_conflict column")

        payload = self._payload if isinstance(self._payload, dict) else self._payload[0]
        stmt = pg_insert(table).values(payload)
        update_values = {key: stmt.excluded[key] for key in payload.keys() if key != self._on_conflict}
        stmt = stmt.on_conflict_do_update(index_elements=[self._on_conflict], set_=update_values).returning(table)

        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def _execute_update(self, table: Table) -> list[dict[str, Any]]:
        if self._payload is None:
            raise ValueError("update payload is required")

        stmt = update(table).values(self._payload)
        where_clause = self._build_where_clause(table)
        if where_clause is not None:
            stmt = stmt.where(where_clause)

        stmt = stmt.returning(table)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def _execute_delete(self, table: Table) -> list[dict[str, Any]]:
        stmt = delete(table)
        where_clause = self._build_where_clause(table)
        if where_clause is not None:
            stmt = stmt.where(where_clause)

        stmt = stmt.returning(table)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]


class PostgresClient:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)

    def table(self, table_name: str) -> PostgresQueryBuilder:
        return PostgresQueryBuilder(self.engine, table_name)
