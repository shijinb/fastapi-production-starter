"""SQLAlchemy models. Every tenant-owned table has an organization_id; queries filter on it in the service layer."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # Store the lowercase values ("admin"), not the member names ("ADMIN").
    return Enum(enum_cls, name=name, values_callable=lambda members: [member.value for member in members])


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class CustomerStatus(enum.StrEnum):
    LEAD = "lead"
    ACTIVE = "active"
    CHURNED = "churned"


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    # E-mail is unique across the whole service: one login identifies exactly one organization.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.MEMBER)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="users")


class RefreshToken(UUIDPrimaryKey, Base):
    """Issued refresh tokens (stored as SHA-256 digests). Rotated on every use; reuse revokes the whole family."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_customers_organization_id_email"),
        CheckConstraint("lifetime_value >= 0", name="lifetime_value_non_negative"),
        Index("ix_customers_organization_id_status", "organization_id", "status"),
        Index("ix_customers_organization_id_created_at", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[CustomerStatus] = mapped_column(_enum(CustomerStatus, "customer_status"), default=CustomerStatus.LEAD)
    lifetime_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditEvent(UUIDPrimaryKey, Base):
    """Append-only record of changes, for "who changed what, when" questions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_audit_events_organization_id_entity_id", "organization_id", "entity_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID]
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = ["AuditEvent", "Customer", "CustomerStatus", "Organization", "RefreshToken", "Role", "User"]
