import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, PaginationDep, SessionDep
from app.models import CustomerStatus
from app.schemas import CustomerCreate, CustomerRead, CustomerStats, CustomerUpdate, Page
from app.services import customers
from app.services.customers import CustomerFilters, SortField

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", summary="Search, filter, sort and paginate customers")
async def list_customers(
    user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(max_length=100, description="Matches name, e-mail or company (case-insensitive).")] = None,
    status_: Annotated[list[CustomerStatus] | None, Query(alias="status", description="Repeat to match several.")] = None,
    owner_id: uuid.UUID | None = None,
    min_lifetime_value: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: SortField = "-created_at",
) -> Page[CustomerRead]:
    filters = CustomerFilters(q=q, status=status_, owner_id=owner_id, min_lifetime_value=min_lifetime_value)
    rows, total = await customers.list_customers(session, user.organization_id, filters, sort, pagination.offset, pagination.page_size)
    return Page[CustomerRead].build([CustomerRead.model_validate(row) for row in rows], total, pagination.page, pagination.page_size)


@router.get("/stats", summary="Counts and lifetime value for the dashboard")
async def customer_stats(user: CurrentUser, session: SessionDep) -> CustomerStats:
    return await customers.stats(session, user.organization_id)


@router.post("", status_code=status.HTTP_201_CREATED, responses={409: {"description": "E-mail already exists"}})
async def create_customer(data: CustomerCreate, user: CurrentUser, session: SessionDep) -> CustomerRead:
    return CustomerRead.model_validate(await customers.create_customer(session, user, data))


@router.get("/{customer_id}", responses={404: {"description": "Not found in your organization"}})
async def get_customer(customer_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CustomerRead:
    return CustomerRead.model_validate(await customers.get_customer(session, user.organization_id, customer_id))


@router.patch("/{customer_id}", summary="Update the fields that are sent")
async def update_customer(customer_id: uuid.UUID, data: CustomerUpdate, user: CurrentUser, session: SessionDep) -> CustomerRead:
    return CustomerRead.model_validate(await customers.update_customer(session, user, customer_id, data))


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer (admin)",
    responses={403: {"description": "Requires admin"}},
)
async def delete_customer(customer_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> None:
    await customers.delete_customer(session, actor, customer_id)
