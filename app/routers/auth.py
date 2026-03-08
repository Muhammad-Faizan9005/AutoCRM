from fastapi import APIRouter, HTTPException, status, Depends
from supabase import Client
from datetime import timedelta
import uuid

from app.database import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
    RefreshTokenRequest,
    TokenResponse
)
from app.auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token
)
from app.auth.dependencies import get_current_user
from app.config import settings

router = APIRouter()


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: RegisterRequest,
    db: Client = Depends(get_db)
):
    """
    Register a new agent/user.
    
    Creates a new agent account with hashed password and returns authentication tokens.
    """
    # Check if user already exists
    existing_user = db.table("agents").select("*").eq("email", user_data.email).execute()
    if existing_user.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash password
    hashed_password = hash_password(user_data.password)
    
    # Create user
    new_user = {
        "id": str(uuid.uuid4()),
        "email": user_data.email,
        "password_hash": hashed_password,
        "full_name": user_data.full_name,
        "role": user_data.role,
        "is_active": True
    }
    
    response = db.table("agents").insert(new_user).execute()
    created_user = response.data[0]
    
    # Create tokens
    access_token = create_access_token(data={"sub": created_user["id"]})
    refresh_token = create_refresh_token(data={"sub": created_user["id"]})
    
    # Remove password hash from response
    created_user.pop("password_hash", None)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": created_user
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    db: Client = Depends(get_db)
):
    """
    Login with email and password.
    
    Returns JWT access and refresh tokens upon successful authentication.
    """
    # Get user by email
    response = db.table("agents").select("*").eq("email", credentials.email).execute()
    
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = response.data[0]
    
    # Verify password
    if not verify_password(credentials.password, user["password_hash"]):
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
    
    # Remove password hash from response
    user.pop("password_hash", None)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user profile.
    
    Requires valid JWT token in Authorization header.
    """
    # Remove password hash if present
    current_user.pop("password_hash", None)
    return current_user


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    refresh_data: RefreshTokenRequest,
    db: Client = Depends(get_db)
):
    """
    Refresh access token using refresh token.
    
    Returns new access and refresh tokens.
    """
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
    response = db.table("agents").select("*").eq("id", user_id).execute()
    if not response.data or not response.data[0].get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create new tokens
    access_token = create_access_token(data={"sub": user_id})
    new_refresh_token = create_refresh_token(data={"sub": user_id})
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60
    }


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout current user.
    
    Note: With JWT, actual logout is handled client-side by removing tokens.
    This endpoint is for logging/audit purposes.
    """
    return {
        "success": True,
        "message": "Successfully logged out"
    }
