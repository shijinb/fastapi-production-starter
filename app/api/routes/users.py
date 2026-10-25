import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminUser, CurrentUser, PaginationDep, SessionDep
from app.schemas import Page, UserCreate, UserRead, UserUpdate
from app.services import users

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", summary="Users in your organization")
async def list_users(user: CurrentUser, session: SessionDep, pagination: PaginationDep) -> Page[UserRead]:
    rows, total = await users.list_users(session, user.organization_id, pagination.offset, pagination.page_size)
    return Page[UserRead].build([UserRead.model_validate(row) for row in rows], total, pagination.page, pagination.page_size)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Add a user to your organization (admin)",
    responses={403: {"description": "Requires admin"}, 409: {"description": "E-mail already registered"}},
)
async def create_user(data: UserCreate, actor: AdminUser, session: SessionDep) -> UserRead:
    return UserRead.model_validate(await users.create_user(session, actor, data))


@router.patch("/{user_id}", summary="Change a user's name, role or active flag (admin)")
async def update_user(user_id: uuid.UUID, data: UserUpdate, actor: AdminUser, session: SessionDep) -> UserRead:
    return UserRead.model_validate(await users.update_user(session, actor, user_id, data))
