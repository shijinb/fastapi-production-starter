"""Request and response models. Responses never include secrets (password hashes, token digests)."""

import math
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import CustomerStatus, Role

Email = Annotated[EmailStr, AfterValidator(lambda value: value.lower())]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Password = Annotated[str, Field(min_length=12, max_length=128, description="12–128 characters.")]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ------------------------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    organization_name: Name
    full_name: Name
    email: Email
    password: Password


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


# --- Users and organizations -----------------------------------------------------------------------


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str


class UserRead(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeResponse(UserRead):
    organization: OrganizationRead


class UserCreate(BaseModel):
    email: Email
    full_name: Name
    password: Password
    role: Literal[Role.ADMIN, Role.MEMBER] = Role.MEMBER


class UserUpdate(BaseModel):
    full_name: Name | None = None
    role: Literal[Role.ADMIN, Role.MEMBER] | None = None
    is_active: bool | None = None


# --- Customers -------------------------------------------------------------------------------------

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class CustomerCreate(BaseModel):
    name: Name
    email: Email
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    status: CustomerStatus = CustomerStatus.LEAD
    lifetime_value: Money = Decimal("0")
    owner_id: uuid.UUID | None = None


class CustomerUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed."""

    name: Name | None = None
    email: Email | None = None
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    status: CustomerStatus | None = None
    lifetime_value: Money | None = None
    owner_id: uuid.UUID | None = None


class CustomerRead(ORMModel):
    id: uuid.UUID
    name: str
    email: str
    company: str | None
    status: CustomerStatus
    lifetime_value: Decimal
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CustomerStats(BaseModel):
    total: int
    by_status: dict[CustomerStatus, int]
    total_lifetime_value: Decimal
    new_last_30_days: int


# --- Audit -----------------------------------------------------------------------------------------


class AuditEventRead(ORMModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    changes: dict[str, Any]
    request_id: str | None
    created_at: datetime


# --- Pagination ------------------------------------------------------------------------------------


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        return cls(items=items, total=total, page=page, page_size=page_size, pages=math.ceil(total / page_size))
