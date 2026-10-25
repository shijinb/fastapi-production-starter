"""Password hashing (Argon2id) and JWT access/refresh tokens."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

_hasher = PasswordHasher()

# Verified against when the e-mail is unknown, so a login for a missing user takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class TokenPayload:
    subject: uuid.UUID
    organization_id: uuid.UUID
    token_type: TokenType
    jti: str
    expires_at: datetime


def create_token(settings: Settings, *, user_id: uuid.UUID, organization_id: uuid.UUID, token_type: TokenType) -> tuple[str, TokenPayload]:
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=settings.access_token_ttl_minutes) if token_type == "access" else timedelta(days=settings.refresh_token_ttl_days)
    )
    payload = TokenPayload(
        subject=user_id,
        organization_id=organization_id,
        token_type=token_type,
        jti=secrets.token_urlsafe(16),
        expires_at=now + ttl,
    )
    token = jwt.encode(
        {
            "sub": str(user_id),
            "org": str(organization_id),
            "type": token_type,
            "jti": payload.jti,
            "iat": now,
            "exp": payload.expires_at,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, payload


class InvalidTokenError(Exception):
    pass


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> TokenPayload:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "org", "type", "jti", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Token is invalid") from exc

    if claims["type"] != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")

    try:
        return TokenPayload(
            subject=uuid.UUID(claims["sub"]),
            organization_id=uuid.UUID(claims["org"]),
            token_type=claims["type"],
            jti=claims["jti"],
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError("Token is invalid") from exc


def fingerprint(token: str) -> str:
    """Refresh tokens are stored as SHA-256 digests, so a database leak does not expose usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()
