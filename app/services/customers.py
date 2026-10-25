"""Customer CRUD, search and statistics. Every query is scoped to the caller's organization."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models import Customer, CustomerStatus, User
from app.schemas import CustomerCreate, CustomerStats, CustomerUpdate
from app.services import audit

SortField = Literal["name", "-name", "created_at", "-created_at", "lifetime_value", "-lifetime_value"]

_SORT_COLUMNS = {"name": Customer.name, "created_at": Customer.created_at, "lifetime_value": Customer.lifetime_value}


@dataclass(frozen=True)
class CustomerFilters:
    q: str | None = None
    status: list[CustomerStatus] | None = None
    owner_id: uuid.UUID | None = None
    min_lifetime_value: Decimal | None = None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(organization_id: uuid.UUID, filters: CustomerFilters) -> Select[Customer]:
    query = select(Customer).where(Customer.organization_id == organization_id)
    if filters.q:
        pattern = f"%{_escape_like(filters.q.strip())}%"
        query = query.where(
            or_(
                Customer.name.ilike(pattern, escape="\\"),
                Customer.email.ilike(pattern, escape="\\"),
                Customer.company.ilike(pattern, escape="\\"),
            )
        )
    if filters.status:
        query = query.where(Customer.status.in_(filters.status))
    if filters.owner_id:
        query = query.where(Customer.owner_id == filters.owner_id)
    if filters.min_lifetime_value is not None:
        query = query.where(Customer.lifetime_value >= filters.min_lifetime_value)
    return query


async def list_customers(
    session: AsyncSession,
    organization_id: uuid.UUID,
    filters: CustomerFilters,
    sort: SortField,
    offset: int,
    limit: int,
) -> tuple[list[Customer], int]:
    query = _filtered(organization_id, filters)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))

    column = _SORT_COLUMNS[sort.lstrip("-")]
    order = column.desc() if sort.startswith("-") else column.asc()
    # Customer.id as a tie-breaker keeps pagination stable when sort values are equal.
    rows = await session.scalars(query.order_by(order, Customer.id).offset(offset).limit(limit))
    return list(rows), total or 0


async def get_customer(session: AsyncSession, organization_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    customer = await session.scalar(select(Customer).where(Customer.id == customer_id, Customer.organization_id == organization_id))
    # Another organization's customer is reported as "not found", never "forbidden", so IDs cannot be probed.
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


async def _check_owner(session: AsyncSession, organization_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
    if owner_id is not None and not await session.scalar(
        select(User.id).where(User.id == owner_id, User.organization_id == organization_id)
    ):
        raise NotFoundError("Owner user not found in this organization")


async def _flush_unique(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("A customer with this e-mail already exists") from exc


async def create_customer(session: AsyncSession, actor: User, data: CustomerCreate) -> Customer:
    await _check_owner(session, actor.organization_id, data.owner_id)
    customer = Customer(organization_id=actor.organization_id, **data.model_dump())
    session.add(customer)
    await _flush_unique(session)
    await session.refresh(customer)

    await audit.record(
        session,
        organization_id=actor.organization_id,
        actor_id=actor.id,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        changes=data.model_dump(),
    )
    return customer


async def update_customer(session: AsyncSession, actor: User, customer_id: uuid.UUID, data: CustomerUpdate) -> Customer:
    customer = await get_customer(session, actor.organization_id, customer_id)
    changes = data.model_dump(exclude_unset=True)
    if "owner_id" in changes:
        await _check_owner(session, actor.organization_id, changes["owner_id"])

    before = {key: getattr(customer, key) for key in changes}
    for key, value in changes.items():
        setattr(customer, key, value)
    await _flush_unique(session)
    await session.refresh(customer)

    if delta := audit.diff(before, changes):
        await audit.record(
            session,
            organization_id=actor.organization_id,
            actor_id=actor.id,
            action="customer.updated",
            entity_type="customer",
            entity_id=customer.id,
            changes=delta,
        )
    return customer


async def delete_customer(session: AsyncSession, actor: User, customer_id: uuid.UUID) -> None:
    customer = await get_customer(session, actor.organization_id, customer_id)
    await session.delete(customer)
    await audit.record(
        session,
        organization_id=actor.organization_id,
        actor_id=actor.id,
        action="customer.deleted",
        entity_type="customer",
        entity_id=customer_id,
        changes={"email": customer.email, "name": customer.name},
    )


async def stats(session: AsyncSession, organization_id: uuid.UUID) -> CustomerStats:
    by_status = dict.fromkeys(CustomerStatus, 0)
    rows = await session.execute(
        select(Customer.status, func.count(), func.coalesce(func.sum(Customer.lifetime_value), 0))
        .where(Customer.organization_id == organization_id)
        .group_by(Customer.status)
    )
    total_value = Decimal("0")
    for status, count, value in rows:
        by_status[status] = count
        total_value += Decimal(value)

    new_last_30_days = await session.scalar(
        select(func.count()).where(
            Customer.organization_id == organization_id,
            Customer.created_at >= datetime.now(UTC) - timedelta(days=30),
        )
    )
    return CustomerStats(
        total=sum(by_status.values()),
        by_status=by_status,
        total_lifetime_value=total_value,
        new_last_30_days=new_last_30_days or 0,
    )
