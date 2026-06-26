import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.database import get_db, run_db_operation
from app.postgres_client import PostgresClient as Client
from app.auth.utils import verify_token
from app.auth.token_store import is_token_blacklisted
from app.utils.cache import get_cached_user, cache_user
from app.services.permission_service import PermissionService

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Client = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get the current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        db: Database client
        
    Returns:
        User/agent dictionary
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = credentials.credentials

    if await is_token_blacklisted(db, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify and decode token
    payload = verify_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Extract user ID from token
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from cache first (90% hit rate expected)
    user = get_cached_user(user_id)
    
    if user is None:
        # Cache miss: fetch from database and cache it
        try:
            response = await run_db_operation(
                lambda: db.table("agents").select("*").eq("id", user_id).single().execute()
            )
            user = response.data
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # Cache user for 5 minutes (TTL on auth checks)
            cache_user(user_id, user, ttl_seconds=300)
            
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            )
    
    # Check if user is active (even from cache, verify this)
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


async def get_current_active_user(current_user: dict = Depends(get_current_user)):
    """
    Get current active user (additional check).
    
    Args:
        current_user: Current user from get_current_user dependency
        
    Returns:
        Active user dictionary
        
    Raises:
        HTTPException: If user is not active
    """
    if not current_user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


async def require_auth(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Explicit dependency alias for protected endpoints.

    Keeps route signatures consistent and reduces the chance of accidentally
    exposing endpoints by forgetting the auth dependency.
    """
    return current_user


async def require_human_or_ai_agent_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    x_ai_agent_key: Optional[str] = Header(default=None, alias="X-AI-Agent-Key"),
    x_ai_service_token: Optional[str] = Header(default=None, alias="X-AI-Service-Token"),
    db: Client = Depends(get_db),
) -> Dict[str, Any]:
    if x_ai_agent_key or x_ai_service_token:
        return await require_ai_agent_auth(x_ai_agent_key, x_ai_service_token, db)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials are required",
        )
    return await get_current_user(credentials, db)


def require_role(allowed_roles: list[str]):
    """
    Dependency factory to require specific roles.
    
    Args:
        allowed_roles: List of allowed role names
        
    Returns:
        Dependency function that checks user role
    """
    async def role_checker(current_user: dict = Depends(get_current_user)):
        user_role = current_user.get("role", "sales_rep")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {allowed_roles}"
            )
        return current_user
    
    return role_checker


def require_admin():
    """Dependency that allows only admin users."""
    return require_role(["admin"])


def require_sales_manager_or_admin():
    """Dependency that allows sales managers and admins."""
    return require_role(["sales_manager", "admin"])


def get_permission_service(db: Client = Depends(get_db)) -> PermissionService:
    return PermissionService(db)


def require_permissions(required_permissions: list[str]):
    """
    Dependency factory to require specific permission keys.

    Permissions are resolved from role defaults plus any stored overrides.
    """

    async def permissions_checker(
        current_user: dict = Depends(get_current_user),
        service: PermissionService = Depends(get_permission_service),
    ) -> dict:
        permissions = await service.get_effective_permissions(current_user)
        missing = [key for key in required_permissions if not permissions.get(key, False)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return permissions_checker


# ---------------------------------------------------------------------------
# AI Service Authentication  (for AI workers, not human users)
# ---------------------------------------------------------------------------

def generate_ai_service_token() -> tuple[str, str, str]:
    """Generate a raw service token, return (raw_token, key_prefix, token_hash)."""
    raw_token = secrets.token_urlsafe(48)
    key_prefix = raw_token[:8]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, key_prefix, token_hash


async def require_ai_agent_auth(
    x_ai_agent_key: Optional[str] = Header(default=None, alias="X-AI-Agent-Key"),
    x_ai_service_token: Optional[str] = Header(default=None, alias="X-AI-Service-Token"),
    db=Depends(get_db),
) -> dict:
    """
    Authenticate incoming requests from AI services.

    Expected headers:
        X-AI-Agent-Key:     e.g. writer_agent
        X-AI-Service-Token: raw service token issued via the admin credential API

    Validates:
        - ai_agents.agent_key exists, enabled=true, status=active
        - ai_agent_credentials row with matching SHA-256 hash, is_active=true
        - credential not expired
    Returns merged AI agent dict with a 'credential_scopes' key.
    """
    if not x_ai_agent_key or not x_ai_service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-AI-Agent-Key and X-AI-Service-Token headers are required",
        )

    # 1. Look up the AI agent
    agent_rows = await run_db_operation(
        lambda: db.table("ai_agents").select("*").eq("agent_key", x_ai_agent_key).limit(1).execute()
    )
    rows = agent_rows.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown AI agent key")
    agent = rows[0]

    if not agent.get("enabled") or str(agent.get("status") or "").lower() != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI agent is disabled or inactive")

    # 2. Verify the token hash
    token_hash = hashlib.sha256(x_ai_service_token.encode()).hexdigest()
    cred_rows = await run_db_operation(
        lambda: db.table("ai_agent_credentials")
            .select("*")
            .eq("ai_agent_id", str(agent["id"]))
            .eq("token_hash", token_hash)
            .eq("is_active", True)
            .limit(5)
            .execute()
    )
    credentials = cred_rows.data or []

    now_iso = datetime.now(timezone.utc).isoformat()
    valid_cred = None
    for cred in credentials:
        expires = cred.get("expires_at")
        if expires is None or str(expires) > now_iso:
            valid_cred = cred
            break

    if not valid_cred:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired service token")

    # 3. Fire-and-forget last_seen / last_used timestamps
    try:
        await run_db_operation(
            lambda: db.table("ai_agents").update({"last_seen_at": now_iso}).eq("id", str(agent["id"])).execute()
        )
        await run_db_operation(
            lambda: db.table("ai_agent_credentials").update({"last_used_at": now_iso}).eq("id", str(valid_cred["id"])).execute()
        )
    except Exception:
        pass

    return {**agent, "credential_scopes": valid_cred.get("scopes") or []}
