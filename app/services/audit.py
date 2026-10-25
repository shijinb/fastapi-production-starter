import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.models import AuditEvent


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value"):  # enums
        return value.value
    if value is not None and not isinstance(value, (str, int, float, bool)):
        return str(value)  # Decimal, datetime
    return value


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{"field": {"from": old, "to": new}} for every field whose value changed."""
    return {key: {"from": _jsonable(before.get(key)), "to": _jsonable(value)} for key, value in after.items() if before.get(key) != value}


async def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    changes: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes={key: _jsonable(value) if not isinstance(value, dict) else value for key, value in (changes or {}).items()},
            request_id=request_id_var.get(),
        )
    )


async def list_events(
    session: AsyncSession, organization_id: uuid.UUID, *, entity_id: uuid.UUID | None, offset: int, limit: int
) -> tuple[list[AuditEvent], int]:
    query = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset(offset).limit(limit))
    return list(rows), total or 0
