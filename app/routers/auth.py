from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets

from fastapi import APIRouter, File, HTTPException, Request, Response, status, Depends, UploadFile
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
from app.auth.cookies import (
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
    set_auth_cookies,
    clear_auth_cookies,
)
from app.auth.dependencies import require_auth, get_permission_service
from app.auth.token_store import blacklist_token, is_token_blacklisted
from app.config import settings
from app.services.permission_service import PermissionService, is_admin_user
from app.services.registration_service import register_user_account
from app.services.email_service import MailjetEmailService

router = APIRouter()

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


def _avatar_url(user_id: str | None) -> str | None:
    """Build the URL for a user's locally-stored avatar.

    Avatars are stored on the backend filesystem and served through the
    /static/avatars mount. Returns None when no avatar exists so the frontend
    falls back to initials. A version query param (file mtime) busts the browser
    cache when the avatar changes.
    """
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


# ---------------------------------------------------------------------------
# S3 AVATAR STORAGE (disabled)
# ---------------------------------------------------------------------------
# Avatars were previously stored in the Supabase S3 bucket via
# app.services.avatar_storage and served through a cached /auth/avatar/{user_id}
# proxy endpoint. This was reverted to local filesystem storage (above) because
# the Supabase storage host is unreachable from the dev network (ISP blocks the
# *.supabase.co domain by SNI). The S3 service + proxy code is kept for
# reference in case we move back to object storage from a reachable environment.
#
# def _avatar_url(user_id: str | None) -> str | None:
#     if not user_id:
#         return None
#     if not avatar_storage.is_enabled():
#         return None
#     found = _cached_avatar_meta(str(user_id))
#     if not found:
#         return None
#     extension, _ = found
#     public_base = settings.AVATAR_PUBLIC_BASE_URL.rstrip("/")
#     return f"{public_base}/api/auth/avatar/{user_id}?ext={extension}"
# ---------------------------------------------------------------------------



def _safe_auth_user(user: dict, permissions: dict[str, bool] | None = None) -> dict:
    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    safe_user["avatar_url"] = _avatar_url(str(safe_user.get("id") or ""))
    raw_settings = safe_user.get("settings")
    if isinstance(raw_settings, str):
        try:
            raw_settings = json.loads(raw_settings)
        except json.JSONDecodeError:
            raw_settings = {}
    settings_payload = raw_settings if isinstance(raw_settings, dict) else {}
    legacy_developer_mode = bool(safe_user.get("developer_mode", False))
    developer_mode = bool(settings_payload.get("developer_mode", legacy_developer_mode))
    if not is_admin_user(safe_user):
        developer_mode = False
    safe_user["settings"] = {**settings_payload, "developer_mode": developer_mode}
    safe_user["developer_mode"] = developer_mode
    if permissions is not None:
        safe_user["permissions"] = permissions
    safe_user["is_admin"] = is_admin_user(safe_user)
    safe_user["is_superuser"] = bool(safe_user.get("is_superuser", False))
    return safe_user


# ---------------------------------------------------------------------------
# LEGACY RUNTIME DDL (disabled — moved to Alembic migrations)
# ---------------------------------------------------------------------------
# This function used to run `ALTER TABLE agents ADD COLUMN IF NOT EXISTS ...`
# on every profile/avatar request to "self-heal" the schema. Against a remote
# DB each ALTER is a full round-trip (~185ms) + an ACCESS EXCLUSIVE lock on
# `agents`, so it added ~0.5s and lock contention to every write — a real
# source of the app slowness. The three columns are now guaranteed by
# migrations instead:
#   - avatar_url     -> r4s5t6u7v8w9_add_agent_avatar_url
#   - settings       -> y1z2a3b4c5d6_add_agent_settings_json
#   - developer_mode -> f8g9h0i1j2k3_formalize_agent_developer_mode
# Run `alembic upgrade head` to apply. Kept commented as a reference.
#
# async def _ensure_profile_columns(db: Client) -> None:
#     def _exec():
#         with db.engine.begin() as conn:
#             conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS avatar_url TEXT"))
#             conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS developer_mode BOOLEAN NOT NULL DEFAULT false"))
#             conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb"))
#
#     await run_db_operation(_exec)
# ---------------------------------------------------------------------------


def _merge_settings(current: object, patch: object, *, allow_developer_mode: bool) -> dict:
    if isinstance(current, str):
        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            current = {}
    base = dict(current) if isinstance(current, dict) else {}
    incoming = dict(patch) if isinstance(patch, dict) else {}
    if not allow_developer_mode:
        incoming.pop("developer_mode", None)

    def merge_dict(left: dict, right: dict) -> dict:
        merged = dict(left)
        for key, value in right.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    return merge_dict(base, incoming)


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
    token: str | None,
) -> None:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can assign this role",
        )

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
    request: Request,
    response: Response,
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    Register a new agent/user.

    By default, registration creates a sales_rep. Admin-authenticated requests can
    assign elevated roles.
    """
    if user_data.role != "sales_rep":
        await _assert_admin_for_role_override(db=db, token=request.cookies.get(ACCESS_TOKEN_COOKIE))

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
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)

    safe_user = _safe_auth_user(
        created_user,
        await permission_service.get_effective_permissions(created_user),
    )

    return {"user": safe_user}


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    response: Response,
    db: Client = Depends(get_db),
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    Login with email and password.

    Issues access and refresh tokens as httpOnly cookies upon successful authentication.
    """
    # Get user by email
    response_data = await run_db_operation(
        lambda: db.table("agents").select("*").eq("email", credentials.email).limit(1).execute()
    )

    if not response_data.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = response_data.data[0]

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
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)

    safe_user = _safe_auth_user(
        user,
        await permission_service.get_effective_permissions(user),
    )

    return {"user": safe_user}


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
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    new_password = update_data.pop("new_password", None)
    current_password = update_data.pop("current_password", None)
    settings_patch = update_data.pop("settings", None)
    developer_mode_patch = update_data.pop("developer_mode", None)
    allowed_fields = {"full_name", "email"}
    update_data = {key: value for key, value in update_data.items() if key in allowed_fields}
    if "email" in update_data and update_data["email"] is not None:
        update_data["email"] = str(update_data["email"]).strip().lower()

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
    if developer_mode_patch is not None:
        settings_patch = {
            **(settings_patch if isinstance(settings_patch, dict) else {}),
            "developer_mode": bool(developer_mode_patch),
        }

    if settings_patch is not None:
        merged_settings = _merge_settings(
            fresh_user.get("settings"),
            settings_patch,
            allow_developer_mode=is_admin_user(fresh_user),
        )
        update_data["settings"] = json.dumps(merged_settings)

    email_changed = (
        "email" in update_data
        and update_data["email"] is not None
        and str(update_data["email"]).lower() != str(fresh_user.get("email") or "").lower()
    )

    if new_password or email_changed:
        stored_hash = fresh_user.get("password_hash")
        if not current_password or not stored_hash or not verify_password(current_password, stored_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    if email_changed:
        def _email_exists():
            with db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT id FROM agents "
                        "WHERE lower(email) = lower(:email) AND id != :user_id "
                        "LIMIT 1"
                    ),
                    {"email": update_data["email"], "user_id": user_id},
                ).mappings().first()
                return bool(row)

        if await run_db_operation(_email_exists):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")

    if new_password:
        update_data["password_hash"] = hash_password(new_password)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    set_clauses = []
    params: dict[str, object] = {"user_id": user_id}
    for key, value in update_data.items():
        if key == "settings":
            set_clauses.append("settings = CAST(:settings AS jsonb)")
        else:
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
    """Upload the current user's avatar to local filesystem storage."""
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
    """Delete the current user's locally-stored avatar."""
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


# ---------------------------------------------------------------------------
# S3 AVATAR UPLOAD / DELETE / PROXY (disabled)
# ---------------------------------------------------------------------------
# The S3-backed versions of the endpoints above, plus a cached
# GET /auth/avatar/{user_id} proxy that streamed bytes from the Supabase bucket,
# were reverted to local filesystem storage (the dev network blocks the Supabase
# storage host by SNI). Local avatars are served directly by the /static/avatars
# mount, so no proxy endpoint is needed. Kept commented for reference:
#
# @router.post("/avatar", ...)  -> avatar_storage.upload_avatar(...)
# @router.delete("/avatar", ...) -> avatar_storage.delete_avatar(...)
# @router.get("/avatar/{user_id}") -> cached avatar_storage.fetch_avatar[_ext](...)
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def refresh_access_token(
    request: Request,
    response: Response,
    db: Client = Depends(get_db),
):
    """
    Refresh the access token using the refresh_token cookie.

    Rotates and re-issues access/refresh/csrf cookies.
    """
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if await is_token_blacklisted(db, refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify refresh token
    payload = verify_token(refresh_token)

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
    user_lookup = await run_db_operation(lambda: db.table("agents").select("*").eq("id", user_id).execute())
    if not user_lookup.data or not user_lookup.data[0].get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create new tokens
    access_token = create_access_token(data={"sub": user_id})
    new_refresh_token = create_refresh_token(data={"sub": user_id})

    # Refresh token rotation: old refresh token is no longer valid.
    await blacklist_token(db, refresh_token, payload.get("exp"))

    set_auth_cookies(response, access_token=access_token, refresh_token=new_refresh_token)

    return {"success": True}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
):
    """
    Logout current user.

    Blacklists the active access/refresh tokens and clears auth cookies.
    """
    access_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if access_token:
        access_payload = verify_token(access_token)
        if access_payload and access_payload.get("exp"):
            await blacklist_token(db, access_token, access_payload.get("exp"))

    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if refresh_token:
        refresh_payload = verify_token(refresh_token)
        if refresh_payload and refresh_payload.get("exp"):
            await blacklist_token(db, refresh_token, refresh_payload.get("exp"))

    clear_auth_cookies(response)

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
