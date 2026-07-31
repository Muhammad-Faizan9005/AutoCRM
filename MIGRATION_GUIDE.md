# Database Migration Guide

Schema changes for the AutoCRM backend are managed with **Alembic**. Alembic is
already configured in this repo; revisions live in `alembic/versions/`.

The project uses a repository layer rather than SQLAlchemy ORM models, so
`target_metadata` is `None` in `alembic/env.py`. Autogenerate will **not** detect
model changes — write migration operations explicitly.

---

## Prerequisites

Set `DATABASE_URL` in `backend/.env` before running any Alembic command.
`alembic/env.py` reads it from settings and fails fast if it is missing or still
the placeholder value.

```env
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=require
```

Get the connection string from your database provider (Supabase, Neon, or other
managed Postgres). For Supabase: **Dashboard → Settings → Database → Connection
string → URI**, then substitute your real password.

Keep credentials in `.env` or a secret manager only — never commit them.

---

## Applying Migrations

```bash
# Apply all pending migrations
python -m alembic upgrade head

# Confirm the applied revision
python -m alembic current
```

Using `python -m alembic` ensures the project root is on `sys.path` so
`app.config` imports resolve.

---

## Command Reference

```bash
# Current revision
python -m alembic current

# Full history
python -m alembic history

# Apply everything / step forward one
python -m alembic upgrade head
python -m alembic upgrade +1

# Roll back one revision / to a specific revision
python -m alembic downgrade -1
python -m alembic downgrade <revision_id>

# Create a new empty revision
python -m alembic revision -m "description_of_change"
```

---

## Creating a New Migration

1. Generate the revision file:

   ```bash
   python -m alembic revision -m "add_avatar_to_agents"
   ```

2. Implement both `upgrade()` and `downgrade()` in the new file under
   `alembic/versions/`:

   ```python
   def upgrade() -> None:
       op.add_column("agents", sa.Column("avatar_url", sa.String(500), nullable=True))


   def downgrade() -> None:
       op.drop_column("agents", "avatar_url")
   ```

3. Apply it:

   ```bash
   python -m alembic upgrade head
   ```

### Common operations

```python
# Index
op.create_index("idx_tickets_status", "tickets", ["status"])
op.drop_index("idx_tickets_status", table_name="tickets")

# Foreign key
op.create_foreign_key(
    "fk_tickets_assigned_to",
    "tickets", "agents",
    ["assigned_to"], ["id"],
    ondelete="SET NULL",
)
op.drop_constraint("fk_tickets_assigned_to", "tickets", type_="foreignkey")
```

### Row Level Security

Several tables are RLS-protected. When adding a table that stores user-scoped
data, add the enabling policy in the same or a follow-up revision — see
`b2c3d4e5f6a1_add_teams_rls.py`, `j2k3l4m5n7_add_rls_leads_calls.py`, and
`t6u7v8w9x0y1_add_customer_organization_rls.py` for the established pattern.

---

## Layout

```
backend/
├── alembic/
│   ├── versions/           # Revision scripts (linear chain)
│   ├── env.py              # Reads DATABASE_URL from app.config
│   ├── script.py.mako
│   └── README
├── alembic.ini
├── database/
│   ├── schema.sql          # Base schema reference
│   └── migrations/         # Legacy raw SQL scripts (historical)
└── .env                    # DATABASE_URL
```

`database/migrations/*.sql` predates Alembic and is kept for reference only.
All new schema changes must go through Alembic.

---

## Troubleshooting

**"Database URL is required before running Alembic migrations"**
`DATABASE_URL` is unset in `backend/.env`, or `alembic.ini` still has the
placeholder `sqlalchemy.url`.

**"Could not connect to database"**
Verify the host, port, password, and `sslmode`. Pooled Supabase connections
typically use port `6543`; direct connections use `5432`.

**"Target database is not up to date"**
The DB is behind the revision chain. Run `python -m alembic upgrade head`, or
`python -m alembic stamp head` if the schema was already applied out-of-band.

**"Column/table already exists"**
The change was applied manually. Either mark it applied with
`python -m alembic stamp <revision>`, or make the migration idempotent
(`IF NOT EXISTS`).

**"Multiple heads detected"**
Two branches were created in parallel:

```bash
python -m alembic heads
python -m alembic merge heads -m "merge_migrations"
```

---

## Production Practices

- Test migrations against staging before production
- Back up the database before applying migrations in production
- Review the generated SQL/operations before applying
- Keep every revision in version control
- Never edit a revision that has already been applied — add a new one
- Always implement `downgrade()` and verify rollback
