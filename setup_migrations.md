# Alembic Setup (Reference)

Alembic is **already installed and configured** in this repository. You do not
need to run `alembic init`. For day-to-day usage — applying, creating, and
rolling back migrations — see `MIGRATION_GUIDE.md`.

This document records how the migration tooling is wired up.

---

## Installed Packages

Declared in `requirements.txt`:

```
sqlalchemy>=2.0.36
alembic>=1.17.0
psycopg2-binary>=2.9.0
```

---

## Configuration

### `alembic.ini`

```ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = .
```

`prepend_sys_path = .` puts the backend root on `sys.path` so `alembic/env.py`
can import `app.config`.

### `alembic/env.py`

The environment resolves the database URL from application settings instead of
hardcoding it, and fails fast when it is missing:

```python
from app.config import settings

config = context.config
runtime_database_url = settings.DATABASE_URL or config.get_main_option("sqlalchemy.url")

if not runtime_database_url or "driver://user:pass@localhost/dbname" in runtime_database_url:
    raise RuntimeError(
        "Database URL is required before running Alembic migrations. "
        "Set DATABASE_URL in backend/.env or sqlalchemy.url in alembic.ini."
    )

config.set_main_option("sqlalchemy.url", runtime_database_url)

# This project uses a repository layer without SQLAlchemy ORM models.
target_metadata = None
```

Because `target_metadata` is `None`, `--autogenerate` cannot diff models.
Every revision must declare its operations explicitly.

Both online and offline modes are configured with `compare_type=True`.

---

## Directory Layout

```
backend/
├── alembic/
│   ├── versions/          # Revision scripts
│   ├── env.py             # Environment configuration
│   ├── script.py.mako     # Template for new revisions
│   └── README
└── alembic.ini            # Alembic configuration
```

---

## Revision Chain

Revisions form a single linear chain and use short descriptive slugs, for
example:

- `945b9872d621_add_password_hash_to_agents.py` — earliest auth revision
- `8c4fe2bde1f9_add_crm_entities.py` — core CRM tables
- `m1n2o3p4q5r6_add_agent_control_plane.py` — AI runs, actions, approvals
- `z2a3b4c5d6e7_add_ai_control_center_indexes.py` — current head

Confirm the live head with:

```bash
python -m alembic heads
python -m alembic current
```

---

## Legacy Raw SQL

`database/migrations/*.sql` contains the pre-Alembic scripts (e.g.
`001_add_password_to_agents.sql`) and `database/schema.sql` holds a base schema
snapshot. These are historical references only — all new schema changes go
through Alembic revisions.

---

## Deployment

Migrations are **not** applied automatically on deploy. The Railway start command
(`railway.json`) and `Procfile` only boot the app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`deploy.sh` / `deploy.ps1` wrap the Railway CLI (`railway up`) and do not run
Alembic either. Apply migrations explicitly against the target database before
or immediately after rolling out a release that requires a schema change:

```bash
python -m alembic upgrade head
```
