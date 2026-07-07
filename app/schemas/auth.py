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
    avatar_url: str | None = None
    role: Literal["admin", "sales_manager", "sales_rep"]
    is_active: bool
    created_at: datetime
    permissions: dict[str, bool] | None = None
    settings: dict | None = None
    developer_mode: bool | None = None
    is_admin: bool | None = None
    is_superuser: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """Login response; tokens are issued as httpOnly cookies, not in the body"""
    user: UserPublic


class RegisterResponse(LoginResponse):
    """Registration response; same contract as login for frontend simplicity"""
    pass


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request schema"""
    token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=6)


class ProfileUpdateRequest(BaseModel):
    """Self-service profile settings update."""
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    email: EmailStr | None = None
    avatar_url: str | None = Field(default=None, max_length=4096)
    developer_mode: bool | None = None
    settings: dict | None = None
    current_password: str | None = Field(default=None, min_length=6)
    new_password: str | None = Field(default=None, min_length=6, max_length=128)


class UserResponse(BaseModel):
    """User profile response"""
    id: UUID
    email: str
    full_name: str
    avatar_url: str | None = None
    role: Literal["admin", "sales_manager", "sales_rep"]
    is_active: bool
    created_at: datetime
    permissions: dict[str, bool] | None = None
    settings: dict | None = None
    is_admin: bool | None = None
    is_superuser: bool | None = None
    developer_mode: bool | None = None
    
    model_config = ConfigDict(from_attributes=True)
