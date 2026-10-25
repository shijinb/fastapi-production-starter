import uuid

from fastapi import APIRouter

from app.api.deps import AdminUser, PaginationDep, SessionDep
from app.schemas import AuditEventRead, Page
from app.services import audit

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", summary="Change history for your organization, newest first (admin)")
async def list_audit_events(
    actor: AdminUser, session: SessionDep, pagination: PaginationDep, entity_id: uuid.UUID | None = None
) -> Page[AuditEventRead]:
    rows, total = await audit.list_events(
        session, actor.organization_id, entity_id=entity_id, offset=pagination.offset, limit=pagination.page_size
    )
    return Page[AuditEventRead].build([AuditEventRead.model_validate(row) for row in rows], total, pagination.page, pagination.page_size)
