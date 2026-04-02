# Running Your First Migration

## ✅ Setup Complete!

I've set up Alembic migrations for your project. Here's what was done:

1. ✅ Installed `alembic` and `psycopg2-binary`
2. ✅ Initialized Alembic in your project
3. ✅ Configured Alembic to use your app settings
4. ✅ Created first migration: `add_password_hash_to_agents`
5. ✅ Updated `requirements.txt`

## 🔧 Before Running Migrations

You need to set up your database connection string in `.env`:

### Get Your Database Password from Supabase:

1. Go to your Supabase Dashboard: https://supabase.com/dashboard
2. Select your project: **AutoCRM**
3. Go to **Settings** (gear icon) → **Database**
4. Scroll to **Connection string** section
5. Select **URI** tab
6. Copy the connection string (it looks like):
   ```
   postgresql://postgres.snwheczzakjyhfaitmoq:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   ```
7. Replace `[YOUR-PASSWORD]` with your actual database password

### Update Your `.env` File:

```env
DATABASE_URL=postgresql://postgres.snwheczzakjyhfaitmoq:[YOUR-ACTUAL-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

**⚠️ IMPORTANT:** Replace `[YOUR-ACTUAL-PASSWORD]` with the real password from Supabase!

## 🚀 Running the Migration

Once you've updated the `DATABASE_URL` in `.env`, run:

```bash
# Apply all pending migrations
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 945b9872d621, add_password_hash_to_agents
```

## ✅ Verify Migration Success

Test if it worked:

```bash
python -c "from app.database import get_db; db = get_db(); result = db.table('agents').select('password_hash').limit(1).execute(); print('✓ password_hash column exists!')"
```

## 📋 Migration Commands Reference

```bash
# View current migration version
alembic current

# View migration history
alembic history

# Apply all migrations
alembic upgrade head

# Apply one migration forward
alembic upgrade +1

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade 945b9872d621

# Create new migration
alembic revision -m "description_of_change"
```

## 🔄 Creating Future Migrations

### Example: Add a new column

1. Create migration:
   ```bash
   alembic revision -m "add_avatar_to_agents"
   ```

2. Edit the generated file in `alembic/versions/`:
   ```python
   def upgrade() -> None:
       op.add_column('agents', 
           sa.Column('avatar_url', sa.String(500), nullable=True)
       )
   
   def downgrade() -> None:
       op.drop_column('agents', 'avatar_url')
   ```

3. Apply migration:
   ```bash
   alembic upgrade head
   ```

### Example: Add an index

```python
def upgrade() -> None:
    op.create_index('idx_tickets_status', 'tickets', ['status'])

def downgrade() -> None:
    op.drop_index('idx_tickets_status', table_name='tickets')
```

### Example: Add a foreign key

```python
def upgrade() -> None:
    op.create_foreign_key(
        'fk_tickets_assigned_to',
        'tickets', 'agents',
        ['assigned_to'], ['id'],
        ondelete='SET NULL'
    )

def downgrade() -> None:
    op.drop_constraint('fk_tickets_assigned_to', 'tickets', type_='foreignkey')
```

## 📁 Project Structure

```
backend/
├── alembic/
│   ├── versions/
│   │   └── 945b9872d621_add_password_hash_to_agents.py
│   ├── env.py              # Configuration
│   └── README
├── alembic.ini             # Alembic settings
├── requirements.txt        # Updated with alembic
└── .env                    # Add DATABASE_URL here
```

## 🐛 Troubleshooting

### "Could not connect to database"
- Check `DATABASE_URL` in `.env` is correct
- Verify database password
- Check internet connection to Supabase

### "Target database is not up to date"
```bash
alembic stamp head
```

### "Column already exists"
The migration was already applied manually. You can:
1. Mark as applied: `alembic stamp head`
2. Or rollback and reapply: `alembic downgrade -1 && alembic upgrade head`

### "Multiple heads detected"
```bash
alembic merge heads -m "merge_migrations"
```

## 🎯 Next Steps

After running your first migration:

1. ✅ The `password_hash` column will be added to `agents` table
2. ✅ Your authentication system will work fully
3. ✅ You can register and login users
4. ✅ Frontend can connect and authenticate

## 🔒 Production Best Practices

- ✅ Always test migrations on staging first
- ✅ Backup database before running migrations in production
- ✅ Review migration code before applying
- ✅ Keep migrations in version control (Git)
- ✅ Never edit applied migrations
- ✅ Write both upgrade() and downgrade() functions
- ✅ Test rollback before deploying

---

**Ready to run?** Update your `.env` with the database password and run:

```bash
alembic upgrade head
```
