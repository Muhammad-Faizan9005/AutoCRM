import asyncio
from app.database import get_db
from app.repositories.agent_control_repository import AiAgentRepository

async def main():
    db = get_db()
    repo = AiAgentRepository(db)
    
    # 1. Direct SQL check
    from sqlalchemy import text
    from app.postgres_client import PostgresClient
    with db.engine.connect() as c:
        rows = c.execute(text("SELECT agent_key, display_name, enabled, status FROM ai_agents ORDER BY display_name")).fetchall()
        print(f"Direct SQL - ai_agents count: {len(rows)}")
        for r in rows:
            print(f"  {r[0]} | {r[1]} | enabled={r[2]} | status={r[3]}")
    
    # 2. Repository check
    try:
        agents = await repo.list_all()
        print(f"\nRepository list_all() count: {len(agents)}")
        for a in agents[:3]:
            print(f"  {a.get('agent_key')} | {a.get('display_name')}")
    except Exception as ex:
        print(f"Repository error: {ex}")
        import traceback; traceback.print_exc()

asyncio.run(main())
