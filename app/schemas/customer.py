from pydantic import BaseModel, EmailStr
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID


CustomerStatus = Literal["active", "inactive", "lead", "churned"]


class CustomerBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    company: Optional[str] = None
    status: Optional[CustomerStatus] = "active"
    notes: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: Optional[CustomerStatus] = None
    notes: Optional[str] = None


class CustomerResponse(CustomerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
