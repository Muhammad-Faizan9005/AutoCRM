from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Any, Dict
from supabase import Client

from app.database import get_db, run_db_operation
from app.auth.utils import verify_token
from app.auth.token_store import is_token_blacklisted
from app.utils.cache import get_cached_user, cache_user
from app.services.permission_service import PermissionService

security = HTTPBearer()


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
