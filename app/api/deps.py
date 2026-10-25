"""FastAPI dependencies: settings, database session, current user and role checks."""

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import InvalidTokenError, decode_token
from app.db.session import session_scope
from app.models import Role, User


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in session_scope(request.app.state.session_factory):
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    try:
        payload = decode_token(settings, credentials.credentials, "access")
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    user = await session.get(User, payload.subject)
    # The organization claim must still match: a user moved between organizations gets no stale access.
    if user is None or not user.is_active or user.organization_id != payload.organization_id:
        raise AuthenticationError("User is not active")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

_ROLE_RANK = {Role.MEMBER: 0, Role.ADMIN: 1, Role.OWNER: 2}


def require_role(minimum: Role) -> Callable[[User], Coroutine[Any, Any, User]]:
    async def check(user: CurrentUser) -> User:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum]:
            raise PermissionDeniedError(f"Requires the {minimum.value} role or higher")
        return user

    return check


AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


PaginationDep = Annotated[Pagination, Depends()]
