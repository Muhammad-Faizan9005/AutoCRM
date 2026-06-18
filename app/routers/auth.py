from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets

from fastapi import APIRouter, File, HTTPException, status, Depends, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from supabase import Client

from app.database import get_db, run_db_operation
from app.utils.cache import invalidate_user_cache
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    RefreshTokenRequest,
    TokenResponse,
    LogoutRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ProfileUpdateRequest,
)
from app.auth.utils import (
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    hash_password,
)
from app.auth.dependencies import require_auth, get_permission_service
from app.auth.token_store import blacklist_token, is_token_blacklisted
from app.config import settings
from app.services.permission_service import PermissionService, is_admin_user
from app.services.registration_service import register_user_account
from app.services.email_service import MailjetEmailService

router = APIRouter()
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

ALLOWED_AVATAR_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_email_service(db: Client = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


def _avatar_storage_dir() -> Path:
    return Path(settings.AVATAR_STORAGE_DIR)


def _local_avatar_url(user_id: str | None) -> str | None:
    if not user_id:
        return None

    avatar_dir = _avatar_storage_dir() / str(user_id)
    for extension in ALLOWED_AVATAR_TYPES.values():
        avatar_path = avatar_dir / f"avatar.{extension}"
        if avatar_path.exists():
            public_base = settings.AVATAR_PUBLIC_BASE_URL.rstrip("/")
            version = avatar_path.stat().st_mtime_ns
            return f"{public_base}/static/avatars/{user_id}/avatar.{extension}?v={version}"
    return None


def _safe_auth_user(user: dict, permissions: dict[str, bool] | None = None) -> dict:
    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    safe_user["avatar_url"] = _local_avatar_url(str(safe_user.get("id") or ""))
    if permissions is not None:
        safe_user["permissions"] = permissions
    safe_user["is_admin"] = is_admin_user(safe_user)
    safe_user["is_superuser"] = bool(safe_user.get("is_superuser", False))
    return safe_user


async def _ensure_profile_columns(db: Client) -> None:
    def _exec():
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS avatar_url TEXT"))

    await run_db_operation(_exec)


async def _return_current_user(
    db: Client,
    permission_service: PermissionService,
    user_id: str,
) -> dict:
    def _fetch_user():
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM agents WHERE id = :user_id"), {"user_id": user_id}).mappings().first()
            return dict(row) if row else None

    user = await run_db_operation(_fetch_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    invalidate_user_cache(user_id)
    permissions = await permission_service.get_effective_permissions(user)
    return _safe_auth_user(user, permissions)


async def _assert_admin_for_role_override(
    db: Client,
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can assign this role",
        )

    token = credentials.credentials
    if await is_token_blacklisted(db, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_payload = verify_token(token)
    if token_payload is None or token_payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    requester_id = token_payload.get("sub")
    if not requester_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    response = await run_db_operation(
        lambda: db.table("agents").select("*").eq("id", requester_id).limit(1).execute()
    )
    requester = (response.data or [None])[0]
    if not requester or requester.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can assign this role",
        )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: RegisterRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    Register a new agent/user.

    By default, registration creates a sales_rep. Admin-authenticated requests can
    assign elevated roles.
    """
    if user_data.role != "sales_rep":
        await _assert_admin_for_role_override(db=db, credentials=credentials)

    created_user = await register_user_account(
        db,
        email=str(user_data.email),
        password=user_data.password,
        full_name=user_data.full_name,
        role=user_data.role,
        is_active=True,
    )
    
    # Create tokens
    access_token = create_access_token(data={"sub": created_user["id"]})
    refresh_token = create_refresh_token(data={"sub": created_user["id"]})
    
    safe_user = _safe_auth_user(
        created_user,
        await permission_service.get_effective_permissions(created_user),
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": safe_user
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    Login with email and password.
    
    Returns JWT access and refresh tokens upon successful authentication.
    """
    # Get user by email
    response = await run_db_operation(
        lambda: db.table("agents").select("*").eq("email", credentials.email).limit(1).execute()
    )
    
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = response.data[0]
    
    # Verify password
    stored_hash = user.get("password_hash")
    if not stored_hash or not verify_password(credentials.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )
    
    # Create tokens
    access_token = create_access_token(data={"sub": user["id"]})
    refresh_token = create_refresh_token(data={"sub": user["id"]})
    
    safe_user = _safe_auth_user(
        user,
        await permission_service.get_effective_permissions(user),
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": safe_user
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: dict = Depends(require_auth),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    Get current authenticated user profile.
    
    Requires valid JWT token in Authorization header.
    """
    return _safe_auth_user(
        current_user,
        await permission_service.get_effective_permissions(current_user),
    )


@router.patch("/profile", response_model=UserResponse)
async def update_current_user_profile(
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """Update the current user's profile settings."""
    await _ensure_profile_columns(db)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    new_password = update_data.pop("new_password", None)
    current_password = update_data.pop("current_password", None)
    allowed_fields = {"full_name"}
    update_data = {key: value for key, value in update_data.items() if key in allowed_fields}

    user_id = str(current_user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    def _fetch_user():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM agents WHERE id = :user_id"),
                {"user_id": user_id},
            ).mappings().first()
            return dict(row) if row else None

    fresh_user = await run_db_operation(_fetch_user)
    if not fresh_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if new_password:
        stored_hash = fresh_user.get("password_hash")
        if not current_password or not stored_hash or not verify_password(current_password, stored_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        update_data["password_hash"] = hash_password(new_password)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    set_clauses = []
    params: dict[str, object] = {"user_id": user_id}
    for key, value in update_data.items():
        set_clauses.append(f"{key} = :{key}")
        params[key] = value
    set_clauses.append("updated_at = NOW()")

    def _update_user():
        with db.engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE agents "
                    f"SET {', '.join(set_clauses)} "
                    "WHERE id = :user_id "
                    "RETURNING *"
                ),
                params,
            ).mappings().first()
            return dict(row) if row else None

    updated_user = await run_db_operation(_update_user)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    invalidate_user_cache(user_id)
    permissions = await permission_service.get_effective_permissions(updated_user)
    return _safe_auth_user(updated_user, permissions)


@router.post("/avatar", response_model=UserResponse)
async def upload_current_user_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """Upload the current user's avatar to local storage."""
    await _ensure_profile_columns(db)

    user_id = str(current_user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    extension = ALLOWED_AVATAR_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a JPG, PNG, WebP, or GIF image")

    contents = await file.read(settings.SUPABASE_MAX_AVATAR_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Avatar image is empty")
    if len(contents) > settings.SUPABASE_MAX_AVATAR_BYTES:
        max_mb = settings.SUPABASE_MAX_AVATAR_BYTES / 1_000_000
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Avatar image must be under {max_mb:g} MB")

    avatar_dir = _avatar_storage_dir() / user_id

    def _save_avatar() -> None:
        avatar_dir.mkdir(parents=True, exist_ok=True)
        for existing_extension in ALLOWED_AVATAR_TYPES.values():
            existing_path = avatar_dir / f"avatar.{existing_extension}"
            if existing_path.exists():
                existing_path.unlink()
        (avatar_dir / f"avatar.{extension}").write_bytes(contents)

    await run_db_operation(_save_avatar)
    return await _return_current_user(db, permission_service, user_id)


@router.delete("/avatar", response_model=UserResponse)
async def delete_current_user_avatar(
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """Delete the current user's locally stored avatar."""
    user_id = str(current_user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    avatar_dir = _avatar_storage_dir() / user_id

    def _delete_avatar() -> None:
        for extension in ALLOWED_AVATAR_TYPES.values():
            avatar_path = avatar_dir / f"avatar.{extension}"
            if avatar_path.exists():
                avatar_path.unlink()

    await run_db_operation(_delete_avatar)
    return await _return_current_user(db, permission_service, user_id)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    refresh_data: RefreshTokenRequest,
    db: Client = Depends(get_db)
):
    """
    Refresh access token using refresh token.
    
    Returns new access and refresh tokens.
    """
    if await is_token_blacklisted(db, refresh_data.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify refresh token
    payload = verify_token(refresh_data.refresh_token)
    
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify user still exists and is active
    response = await run_db_operation(lambda: db.table("agents").select("*").eq("id", user_id).execute())
    if not response.data or not response.data[0].get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create new tokens
    access_token = create_access_token(data={"sub": user_id})
    new_refresh_token = create_refresh_token(data={"sub": user_id})

    # Refresh token rotation: old refresh token is no longer valid.
    await blacklist_token(db, refresh_data.refresh_token, payload.get("exp"))
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/logout")
async def logout(
    payload: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
):
    """
    Logout current user.
    
    Note: With JWT, actual logout is handled client-side by removing tokens.
    This endpoint is for logging/audit purposes and to invalidate cached user data.
    """
    access_payload = verify_token(credentials.credentials)
    if access_payload and access_payload.get("exp"):
        await blacklist_token(db, credentials.credentials, access_payload.get("exp"))

    refresh_token = payload.refresh_token if payload else None
    if refresh_token:
        refresh_payload = verify_token(refresh_token)
        if refresh_payload and refresh_payload.get("exp"):
            await blacklist_token(db, refresh_token, refresh_payload.get("exp"))

    # Invalidate user cache on logout
    user_id = current_user.get("id")
    if user_id:
        invalidate_user_cache(user_id)

    return {
        "success": True,
        "message": "Successfully logged out"
    }


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: Client = Depends(get_db),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    response = await run_db_operation(
        lambda: db.table("agents").select("id,email").eq("email", str(payload.email)).limit(1).execute()
    )
    user = (response.data or [None])[0]

    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_TTL_MINUTES)

        def _store():
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE password_reset_tokens
                        SET used_at = NOW()
                        WHERE user_id = :uid AND used_at IS NULL;
                        """
                    ),
                    {"uid": str(user["id"])},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                        VALUES (:uid, :token_hash, :expires_at);
                        """
                    ),
                    {
                        "uid": str(user["id"]),
                        "token_hash": token_hash,
                        "expires_at": expires_at,
                    },
                )

        await run_db_operation(_store)

        reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
        await email_service.send_password_reset_email(
            recipient_email=str(user["email"]),
            reset_link=reset_link,
            ttl_minutes=settings.RESET_TOKEN_TTL_MINUTES,
        )

    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: Client = Depends(get_db),
):
    token_hash = _hash_reset_token(payload.token)

    def _fetch_token():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, user_id, expires_at, used_at
                    FROM password_reset_tokens
                    WHERE token_hash = :token_hash
                    LIMIT 1;
                    """
                ),
                {"token_hash": token_hash},
            ).mappings().first()
            return dict(row) if row else None

    record = await run_db_operation(_fetch_token)
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    now = datetime.now(timezone.utc)
    if record.get("used_at") or record.get("expires_at") <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    def _apply_reset():
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE agents
                    SET password_hash = :password_hash
                    WHERE id = :user_id;
                    """
                ),
                {
                    "user_id": str(record["user_id"]),
                    "password_hash": hash_password(payload.password),
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE password_reset_tokens
                    SET used_at = NOW()
                    WHERE id = :token_id;
                    """
                ),
                {"token_id": str(record["id"])},
            )

    await run_db_operation(_apply_reset)
    invalidate_user_cache(str(record["user_id"]))

    return {"message": "Password reset successful"}
