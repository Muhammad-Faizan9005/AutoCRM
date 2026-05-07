from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Literal
from uuid import UUID
from datetime import datetime


class LoginRequest(BaseModel):
    """Login request schema"""
    email: EmailStr
    password: str = Field(..., min_length=6)


class RegisterRequest(BaseModel):
    """Agent registration request schema"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2, max_length=255)
    role: Literal["admin", "sales_manager", "sales_rep"] = "sales_rep"


class UserPublic(BaseModel):
    """Safe user payload for API responses"""
    id: UUID
    email: str
    full_name: str
    role: Literal["admin", "sales_manager", "sales_rep"]
    is_active: bool
    created_at: datetime
    permissions: dict[str, bool] | None = None
    is_admin: bool | None = None
    is_superuser: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    """Token response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class LoginResponse(BaseModel):
    """Login response with tokens and user data"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic


class RegisterResponse(LoginResponse):
    """Registration response; same contract as login for frontend simplicity"""
    pass


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Optional logout payload for invalidating refresh token."""
    refresh_token: str | None = None


class UserResponse(BaseModel):
    """User profile response"""
    id: UUID
    email: str
    full_name: str
    role: Literal["admin", "sales_manager", "sales_rep"]
    is_active: bool
    created_at: datetime
    permissions: dict[str, bool] | None = None
    is_admin: bool | None = None
    is_superuser: bool | None = None
    
    model_config = ConfigDict(from_attributes=True)
