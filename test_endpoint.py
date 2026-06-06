import asyncio
from app.main import app
from fastapi.testclient import TestClient

# Check the route is registered
ai_routes = [(list(r.methods), r.path) for r in app.routes if hasattr(r, "path") and "ai-agent" in r.path]
print("Registered AI agent routes:")
for methods, path in ai_routes:
    print(f"  {methods} {path}")

if not ai_routes:
    print("ERROR: No ai-agent routes found - backend needs restart!")
else:
    print("\nRoute check OK - backend has the new endpoints")
