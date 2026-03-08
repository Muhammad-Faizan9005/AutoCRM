# Setting Up Database Migrations with Alembic

## Installation

```bash
pip install alembic
pip freeze > requirements.txt
```

## Initialize Alembic

```bash
cd backend
alembic init alembic
```

This creates:
```
backend/
├── alembic/
│   ├── versions/          # Migration files go here
│   ├── env.py            # Environment configuration
│   └── script.py.mako    # Template for new migrations
└── alembic.ini           # Alembic configuration
```

## Configure for Supabase

Edit `alembic/env.py`:

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.config import settings

# Import your models here if using SQLAlchemy
# from app.models import Base
# target_metadata = Base.metadata

# For now, we'll use None and write SQL migrations
target_metadata = None

config = context.config

# Override sqlalchemy.url with Supabase connection string
config.set_main_option(
    'sqlalchemy.url',
    settings.DATABASE_URL or f"postgresql://postgres:{settings.SUPABASE_KEY}@db.{settings.SUPABASE_URL.split('//')[1].split('.')[0]}.supabase.co:5432/postgres"
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

## Create Your First Migration

```bash
alembic revision -m "add_password_hash_to_agents"
```

This creates a new file in `alembic/versions/`. Edit it:

```python
"""add_password_hash_to_agents

Revision ID: abc123
Revises: 
Create Date: 2026-03-08

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'abc123'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Add password_hash column to agents table"""
    op.add_column('agents', 
        sa.Column('password_hash', sa.String(255), nullable=True)
    )
    
    # After adding, make it NOT NULL (after ensuring all records have values)
    # op.alter_column('agents', 'password_hash', nullable=False)

def downgrade() -> None:
    """Remove password_hash column from agents table"""
    op.drop_column('agents', 'password_hash')
```

## Run Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Check current version
alembic current

# View migration history
alembic history

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123
```

## Workflow

### 1. Make Database Changes

```bash
# Create new migration
alembic revision -m "descriptive_name"

# Edit the generated file in alembic/versions/
# Write upgrade() and downgrade() functions
```

### 2. Test Locally

```bash
# Apply migration
alembic upgrade head

# Test your application
# If issues, rollback
alembic downgrade -1
```

### 3. Commit to Git

```bash
git add alembic/versions/xxx_descriptive_name.py
git commit -m "Add migration: descriptive_name"
git push
```

### 4. Deploy to Production

```bash
# On production server
git pull
alembic upgrade head
```

## Common Migration Patterns

### Add Column
```python
def upgrade():
    op.add_column('table_name', 
        sa.Column('column_name', sa.String(255), nullable=True)
    )
```

### Remove Column
```python
def upgrade():
    op.drop_column('table_name', 'column_name')
```

### Add Index
```python
def upgrade():
    op.create_index('idx_table_column', 'table_name', ['column_name'])
```

### Modify Column
```python
def upgrade():
    op.alter_column('table_name', 'column_name',
        type_=sa.String(500),
        nullable=False
    )
```

### Add Foreign Key
```python
def upgrade():
    op.create_foreign_key(
        'fk_tickets_customer',
        'tickets', 'customers',
        ['customer_id'], ['id']
    )
```

## Integration with CI/CD

Add to your deployment script:

```bash
#!/bin/bash
# deploy.sh

echo "Running database migrations..."
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✓ Migrations completed successfully"
    echo "Starting application..."
    uvicorn app.main:app --host 0.0.0.0 --port 8000
else
    echo "✗ Migration failed"
    exit 1
fi
```

## Best Practices

1. **Always write both upgrade() and downgrade()**
   - Even if you never rollback, it documents the change

2. **One change per migration**
   - Easier to rollback specific changes
   - Better for code review

3. **Test migrations before production**
   - Run on staging environment first
   - Test rollback as well

4. **Never edit applied migrations**
   - Create a new migration to fix issues
   - Preserves migration history

5. **Use descriptive names**
   - `add_password_hash_to_agents` not `migration1`

6. **Add comments**
   - Explain why the change was made
   - Document any data transformations

7. **Handle data migrations carefully**
   - Separate schema changes from data changes
   - Test with production-like data volume

## Troubleshooting

### "Target database is not up to date"
```bash
alembic stamp head
```

### "Multiple heads detected"
```bash
alembic merge heads -m "merge_migrations"
```

### "Connection refused"
- Check DATABASE_URL in .env
- Verify Supabase credentials
- Check network connectivity

## Alternative: Simple Custom System

If Alembic feels too heavy, use this simple approach:

```python
# backend/migrate.py
import os
from app.database import get_db

MIGRATIONS_DIR = "database/migrations"
APPLIED_FILE = "database/.applied_migrations"

def get_applied_migrations():
    if not os.path.exists(APPLIED_FILE):
        return set()
    with open(APPLIED_FILE, 'r') as f:
        return set(line.strip() for line in f)

def mark_migration_applied(filename):
    with open(APPLIED_FILE, 'a') as f:
        f.write(f"{filename}\n")

def run_migrations():
    applied = get_applied_migrations()
    db = get_db()
    
    # Get all SQL files
    migrations = sorted([
        f for f in os.listdir(MIGRATIONS_DIR) 
        if f.endswith('.sql')
    ])
    
    for migration_file in migrations:
        if migration_file in applied:
            print(f"⏭️  Skipping {migration_file} (already applied)")
            continue
        
        print(f"🔄 Applying {migration_file}...")
        filepath = os.path.join(MIGRATIONS_DIR, migration_file)
        
        with open(filepath, 'r') as f:
            sql = f.read()
        
        try:
            # Execute via Supabase requires using their SQL editor
            # or psycopg2 with direct connection
            print(f"⚠️  Run manually in Supabase SQL editor:")
            print(sql)
            
            # Mark as applied after manual confirmation
            # mark_migration_applied(migration_file)
            # print(f"✅ Applied {migration_file}")
        except Exception as e:
            print(f"❌ Failed to apply {migration_file}: {e}")
            break

if __name__ == "__main__":
    run_migrations()
```

Usage:
```bash
python migrate.py
```
