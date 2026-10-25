"""Registration, login and refresh-token rotation.

Refresh tokens are single-use. Each use issues a new token in the same "family" and revokes the old
one. If an already-used token is presented again, it was probably stolen, so every token in its
family is revoked and the user has to log in again (OAuth 2.0 Security BCP, refresh token rotation).
"""

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    fingerprint,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models import Organization, RefreshToken, Role, User
from app.schemas import RegisterRequest, TokenResponse
from app.services import audit

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{slug}-{secrets.token_hex(3)}"


async def register(session: AsyncSession, data: RegisterRequest) -> User:
    if await session.scalar(select(User.id).where(User.email == data.email)):
        raise ConflictError("An account with this e-mail already exists")

    organization = Organization(name=data.organization_name, slug=_slugify(data.organization_name))
    user = User(
        organization=organization,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=Role.OWNER,
    )
    session.add_all([organization, user])
    try:
        await session.flush()
    except IntegrityError as exc:  # concurrent registration with the same e-mail
        raise ConflictError("An account with this e-mail already exists") from exc

    await audit.record(
        session,
        organization_id=organization.id,
        actor_id=user.id,
        action="organization.created",
        entity_type="organization",
        entity_id=organization.id,
        changes={"name": organization.name},
    )
    logger.info("Organization registered", extra={"organization_id": str(organization.id)})
    return user


async def _issue_tokens(session: AsyncSession, settings: Settings, user: User, family_id: uuid.UUID | None = None) -> TokenResponse:
    access_token, _ = create_token(settings, user_id=user.id, organization_id=user.organization_id, token_type="access")
    refresh_token, refresh_payload = create_token(settings, user_id=user.id, organization_id=user.organization_id, token_type="refresh")
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=fingerprint(refresh_token),
            family_id=family_id or uuid.uuid4(),
            expires_at=refresh_payload.expires_at,
        )
    )
    await session.flush()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


async def login(session: AsyncSession, settings: Settings, email: str, password: str) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == email))

    # verify_password runs even when the user does not exist, so response time does not reveal valid e-mails.
    if not verify_password(password, user.password_hash if user else None) or user is None:
        logger.info("Login failed", extra={"reason": "bad_credentials"})
        raise AuthenticationError("Incorrect e-mail or password")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)

    return await _issue_tokens(session, settings, user)


async def refresh(session: AsyncSession, settings: Settings, refresh_token: str) -> TokenResponse:
    try:
        payload = decode_token(settings, refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    stored = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == fingerprint(refresh_token)).with_for_update())
    if stored is None or stored.user_id != payload.subject:
        raise AuthenticationError("Refresh token is not recognised")

    now = datetime.now(UTC)
    if stored.revoked_at is not None:
        await revoke_family(session, stored.family_id, now)
        # The revocation must persist even though this request fails.
        await session.commit()
        logger.warning("Refresh token reuse detected; token family revoked", extra={"user_id": str(stored.user_id)})
        raise AuthenticationError("Refresh token has already been used")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("This account is disabled")

    stored.revoked_at = now
    return await _issue_tokens(session, settings, user, family_id=stored.family_id)


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime | None = None) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )


async def logout(session: AsyncSession, settings: Settings, refresh_token: str) -> None:
    """Revokes the session the refresh token belongs to. Unknown or expired tokens are ignored."""
    stored = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == fingerprint(refresh_token)))
    if stored is not None:
        await revoke_family(session, stored.family_id)
