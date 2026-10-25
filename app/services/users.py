import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import hash_password
from app.models import RefreshToken, Role, User
from app.schemas import UserCreate, UserUpdate
from app.services import audit


async def list_users(session: AsyncSession, organization_id: uuid.UUID, offset: int, limit: int) -> tuple[list[User], int]:
    query = select(User).where(User.organization_id == organization_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(User.created_at, User.id).offset(offset).limit(limit))
    return list(rows), total or 0


async def get_user(session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await session.scalar(select(User).where(User.id == user_id, User.organization_id == organization_id))
    if user is None:
        raise NotFoundError("User not found")
    return user


async def create_user(session: AsyncSession, actor: User, data: UserCreate) -> User:
    if await session.scalar(select(User.id).where(User.email == data.email)):
        raise ConflictError("An account with this e-mail already exists")

    user = User(
        organization_id=actor.organization_id,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("An account with this e-mail already exists") from exc

    await audit.record(
        session,
        organization_id=actor.organization_id,
        actor_id=actor.id,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        changes={"email": user.email, "role": user.role},
    )
    return user


async def update_user(session: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = await get_user(session, actor.organization_id, user_id)
    if user.role == Role.OWNER:
        raise PermissionDeniedError("The organization owner cannot be changed through this endpoint")
    if user.id == actor.id and (data.role is not None or data.is_active is False):
        raise PermissionDeniedError("You cannot change your own role or deactivate yourself")

    changes = data.model_dump(exclude_unset=True)
    before = {key: getattr(user, key) for key in changes}
    for key, value in changes.items():
        setattr(user, key, value)

    if data.is_active is False:
        # Deactivation ends existing sessions: refresh tokens stop working immediately.
        await session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=func.now())
        )

    if delta := audit.diff(before, changes):
        await audit.record(
            session,
            organization_id=actor.organization_id,
            actor_id=actor.id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            changes=delta,
        )
    await session.flush()
    return user
