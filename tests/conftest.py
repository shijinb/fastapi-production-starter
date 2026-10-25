"""Tests run against a real PostgreSQL database, migrated with Alembic (so the migrations are tested too).

Set TEST_DATABASE_URL, e.g. postgresql+asyncpg://postgres:postgres@localhost:5432/starter_test.
The database is created if missing, migrated once per session, and truncated between tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.session import create_engine, create_session_factory
from app.main import create_app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/starter_test")
TABLES = "audit_events, refresh_tokens, customers, users, organizations"


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = await asyncpg.connect(
        host=parsed.host, port=parsed.port or 5432, user=parsed.username, password=parsed.password, database="postgres"
    )
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", parsed.database):
            await admin.execute(f'CREATE DATABASE "{parsed.database}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    asyncio.run(_ensure_database(TEST_DATABASE_URL))
    config = Config("alembic.ini")
    config.attributes["database_url"] = TEST_DATABASE_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def settings(migrated_database: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=migrated_database,
        jwt_secret="test-secret-that-is-at-least-32-characters-long",  # type: ignore[arg-type]
        log_json=False,
        log_level="WARNING",
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    await engine.dispose()


async def register(client: AsyncClient, email: str = "owner@acme.example.com", org: str = "Acme Ltd") -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"organization_name": org, "full_name": "Olivia Owner", "email": email, "password": "correct horse battery"},
    )
    assert response.status_code == 201, response.text
    tokens: dict[str, Any] = response.json()
    return tokens


def bearer(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture
async def owner(client: AsyncClient) -> dict[str, str]:
    return bearer(await register(client))


async def add_user(client: AsyncClient, admin: dict[str, str], email: str, role: str = "member") -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": email, "full_name": email.split("@")[0].title(), "password": "another long password", "role": role},
    )
    assert created.status_code == 201, created.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "another long password"})
    return bearer(login.json())
