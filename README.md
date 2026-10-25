# FastAPI Production Starter

A multi-tenant FastAPI service with the parts real SaaS backends need from day one: **JWT authentication with refresh-token rotation, role-based access, tenant isolation, an audit log, Alembic migrations, structured logging, consistent error responses, health checks, Docker and CI**, all exercised by tests against a real PostgreSQL database.

[![CI](https://github.com/shijinb/fastapi-production-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/shijinb/fastapi-production-starter/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

```bash
git clone https://github.com/shijinb/fastapi-production-starter.git && cd fastapi-production-starter
docker compose up --build                                # Postgres + migrations + API on :8000
docker compose run --rm api python -m scripts.seed       # demo organization, users and 120 customers
open http://localhost:8000/docs                          # interactive API docs
```

The example domain is a small CRM (organizations, users, customers), chosen so the patterns are concrete. Replace it with your own resources and keep the structure.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [API](#api)
- [Authentication and authorization](#authentication-and-authorization)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Database and migrations](#database-and-migrations)
- [Testing](#testing)
- [Deployment notes](#deployment-notes)
- [Security](#security)
- [Limitations](#limitations)

## Features

| Area | What's included |
|---|---|
| **Auth** | Registration (creates an organization and its owner), login, Argon2id password hashing with automatic rehash, 15-minute access tokens, 14-day refresh tokens stored only as SHA-256 digests |
| **Session security** | Refresh tokens are single-use and rotated on every refresh; presenting a used token revokes the whole session ("token family"); logout and user deactivation revoke sessions immediately |
| **Multi-tenancy** | Every tenant-owned row has `organization_id`; every query is scoped in the service layer; other tenants' records return 404, so IDs cannot be probed |
| **RBAC** | `owner` > `admin` > `member`; admins manage users and delete customers; the owner cannot be modified via the API; users cannot demote or disable themselves |
| **Example resource** | Customers: create, read, partial update, delete; search across name, e-mail and company (LIKE wildcards escaped); multi-status filter; sort; pagination; dashboard statistics |
| **Audit log** | Append-only record of who changed what, storing only fields whose value changed, with the request ID for log correlation |
| **Errors** | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `application/problem+json` for every error, including validation errors with field locations; unexpected errors never leak internals |
| **Observability** | JSON logs (one line per request with method, path, status and duration), `X-Request-ID` accepted or generated and returned, `/health` and `/ready` (checks the database) |
| **Operations** | Alembic migrations (tested up, down and up again), Docker image running as a non-root user with a health check, docker-compose stack, seed script, GitHub Actions CI |

## Architecture

```mermaid
flowchart LR
    C[Client / admin dashboard] -->|HTTPS| N[Reverse proxy]
    N --> M[RequestContextMiddleware<br/>request ID · access log]
    M --> R[Routers<br/>app/api/routes]
    R --> D[Dependencies<br/>auth · role checks · pagination]
    R --> S[Services<br/>app/services]
    S --> A[(Audit log)]
    S --> DB[(PostgreSQL<br/>SQLAlchemy 2 async)]
    R -.errors.-> E[Problem-details handlers]
```

```
app/
  main.py              app factory, middleware, routers, lifespan (engine + session factory)
  middleware.py        request ID + access log (pure ASGI)
  core/                config (pydantic-settings), security (Argon2, JWT), errors, logging
  db/                  declarative base with naming conventions, engine and session scope
  models/              Organization, User, RefreshToken, Customer, AuditEvent
  schemas/             request/response models, generic Page[T]
  services/            business logic: auth, users, customers, audit (all tenant-scoped)
  api/deps.py          settings, session, current user, role checks, pagination
  api/routes/          health, auth, users, customers, audit-events
alembic/               migrations (async env)
scripts/seed.py        synthetic demo data
tests/                 30 tests against PostgreSQL
```

**Design choices**

- **Routers stay thin.** Validation happens in Pydantic schemas; rules and queries live in services, which take an explicit `organization_id` so tenant scoping is visible in every query.
- **One transaction per request.** The session dependency commits on success and rolls back on any exception. Refresh-token reuse is the one deliberate exception: the revocation is committed even though the request fails.
- **App factory.** `create_app(settings)` lets tests build an app with their own settings and database.

## API

Base path `/api/v1`. Interactive docs at `/docs` (Swagger UI) and `/redoc`; OpenAPI schema at `/openapi.json`.

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/register` | public | Create an organization and its owner; returns tokens |
| POST | `/auth/login` | public | E-mail + password → access and refresh tokens |
| POST | `/auth/refresh` | public | Rotate a refresh token |
| POST | `/auth/logout` | public | Revoke the session of a refresh token |
| GET | `/auth/me` | any | Current user and organization |
| GET | `/users` | any | Users in your organization (paginated) |
| POST | `/users` | admin | Add a user (`admin` or `member`) |
| PATCH | `/users/{id}` | admin | Change name, role or active flag |
| GET | `/customers` | any | Search, filter, sort, paginate |
| GET | `/customers/stats` | any | Totals by status, lifetime value, new in last 30 days |
| POST | `/customers` | any | Create |
| GET | `/customers/{id}` | any | Read |
| PATCH | `/customers/{id}` | any | Partial update |
| DELETE | `/customers/{id}` | admin | Delete |
| GET | `/audit-events` | admin | Change history, optional `entity_id` filter |
| GET | `/health`, `/ready` | public | Liveness / readiness (outside `/api/v1`) |

**List parameters (`GET /customers`):** `q` (name, e-mail or company), `status` (repeatable: `lead`, `active`, `churned`), `owner_id`, `min_lifetime_value`, `sort` (`name`, `created_at`, `lifetime_value`, prefix `-` for descending; default `-created_at`), `page` (from 1), `page_size` (1–100, default 20).

```bash
curl -s "http://localhost:8000/api/v1/customers?q=northwind&status=active&sort=-lifetime_value&page_size=2" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {"id": "…", "name": "Jonas Silva", "email": "jonas.silva…@customers.example.com", "company": "Northwind",
     "status": "active", "lifetime_value": "3247.34", "owner_id": "…", "created_at": "…", "updated_at": "…"}
  ],
  "total": 3, "page": 1, "page_size": 2, "pages": 2
}
```

Errors (example: a member trying to delete):

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "detail": "Requires the admin role or higher",
  "instance": "/api/v1/customers/6f1c…",
  "request_id": "d02d02eaf24c48a49a1d205e822dbe75"
}
```

## Authentication and authorization

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API
    participant DB as PostgreSQL
    C->>A: POST /auth/login (e-mail, password)
    A->>DB: verify Argon2 hash, store SHA-256(refresh token) in family F
    A-->>C: access (15 min) + refresh (14 days)
    C->>A: API calls with Bearer access token
    C->>A: POST /auth/refresh (R1)
    A->>DB: revoke R1, issue R2 in family F
    A-->>C: new access + R2
    Note over C,A: If R1 is ever presented again,<br/>every token in family F is revoked
```

- Tokens are HS256 JWTs with `sub` (user), `org` (organization), `type` (`access`/`refresh`), `jti`, `iat` and `exp`; the type is checked, so a refresh token cannot be used as an access token.
- On every request the user is reloaded: deactivated users, or users whose organization no longer matches the token, are rejected immediately, not when the token expires.
- Login spends the same Argon2 verification time for unknown e-mails as for wrong passwords, and returns the same message for both.

## Local development

Requirements: Python 3.12, PostgreSQL 14+ (or Docker).

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # set DATABASE_URL and JWT_SECRET
alembic upgrade head
python -m scripts.seed               # demo users: owner@ / admin@ / member@demo.example.com
uvicorn app.main:app --reload        # http://localhost:8000/docs
```

Demo password for seeded users: `demo-password-change-me`. All seeded people and companies are fictional.

`make install | dev | test | lint | migrate | seed | up | down` wraps these commands.

## Configuration

Environment variables (or `.env`); see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` enables the secret check below |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/app` | Must use the `asyncpg` driver |
| `DATABASE_POOL_SIZE` | `5` | Per process |
| `JWT_SECRET` | dev placeholder | **Required in production**, at least 32 characters; startup fails otherwise |
| `JWT_ALGORITHM` | `HS256` | `HS256`, `HS384` or `HS512` |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | 1–1440 |
| `REFRESH_TOKEN_TTL_DAYS` | `14` | 1–90 |
| `CORS_ORIGINS` | none | Comma-separated or JSON list; CORS is off when empty |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Text logs with `LOG_JSON=false` |
| `DOCS_ENABLED` | `true` | Set `false` to hide `/docs`, `/redoc`, `/openapi.json` |

## Database and migrations

| Table | Purpose |
|---|---|
| `organizations` | Tenants |
| `users` | Belongs to one organization; e-mail unique across the service; role enum |
| `refresh_tokens` | SHA-256 digest, family ID, expiry, revocation time |
| `customers` | Tenant-owned; unique `(organization_id, email)`; `lifetime_value >= 0` check; indexes for status and date filters |
| `audit_events` | Append-only; indexed by `(organization_id, created_at)` and `(organization_id, entity_id)` |

```bash
alembic upgrade head                                 # apply
alembic revision --autogenerate -m "describe change" # after editing app/models
alembic check                                        # fails if models and migrations differ (run in CI)
```

Constraint names follow a fixed naming convention, so autogenerated migrations are stable and reviewable.

## Testing

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/starter_test
pytest            # creates the database if missing, migrates it with Alembic, truncates between tests
make lint         # ruff format/check, mypy --strict
```

30 tests cover:
- **Auth:** registration, duplicate and case-insensitive e-mail, login messages that don't reveal accounts, token type checks, rotation, reuse detection revoking the session, logout, immediate effect of deactivation.
- **Tenancy:** another organization's data is invisible to list, get, update, delete, stats and users; the same customer e-mail is allowed in different tenants.
- **Roles:** member and admin rules, owner protection, no self-demotion.
- **Customers:** validation, normalisation, search with literal `%`/`_`, filters, sorting, pagination, partial updates, stats.
- **Platform:** audit trail content and access, problem-details format, request-ID handling, health and readiness, OpenAPI coverage, production config guards.

**Verification status (2026-10-25):** the 30 tests, `ruff` and `mypy --strict` pass locally on Python 3.12 with PostgreSQL 15. Migrations were run up, down and up again, and `alembic check` reports no drift. The server was started with uvicorn and exercised with real requests: login, stats, search and docs. In GitHub Actions (CI run #1), the same checks passed against PostgreSQL 16, and the Docker job built the image, started the compose stack, seeded data, logged in and queried the API.

## Deployment notes

- Run `alembic upgrade head` as a release step before starting new API containers (the compose file models this as the `migrate` service), not on every container start.
- Put the API behind a reverse proxy that terminates TLS. Uvicorn is started with `--proxy-headers`, so restrict `--forwarded-allow-ips` to your proxy's address in production.
- Scale horizontally: the API is stateless. Set `DATABASE_POOL_SIZE` × instances below the database's connection limit, or use a pooler such as PgBouncer.
- Point load balancer health checks at `/ready` (database reachable) and container liveness at `/health`.
- A worked AWS deployment (Docker, Nginx, GitHub Actions) is planned for a separate `aws-deployment-lab` repository.

## Security

- Secrets only from the environment; production refuses to start with a missing or short `JWT_SECRET`.
- Passwords: Argon2id (argon2-cffi defaults), 12–128 characters, rehashed when parameters change.
- Refresh tokens stored as SHA-256 digests; rotation with reuse detection; sessions revoked on logout and deactivation.
- Tenant scoping in every query; cross-tenant access returns 404.
- LIKE wildcards in search are escaped; all SQL goes through SQLAlchemy parameters.
- Errors return no stack traces; details are logged with the request ID.
- The container runs as a non-root user.

Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Limitations

These are deliberately out of scope for a starter, and should be added before production use where needed:

- **No rate limiting** on login or registration. Add it at the proxy (e.g. Nginx `limit_req`) or with a Redis-backed limiter.
- **No e-mail verification, password reset or invitation e-mails** (these need an e-mail provider).
- **One organization per user.** Users who belong to several tenants need a membership table.
- **HS256 shared secret.** Use RS256/EdDSA with key rotation if other services must verify tokens.
- **Search uses `ILIKE '%term%'`**, fine for thousands of rows. Add a `pg_trgm` index or a search engine for large tables.
- **Expired refresh-token rows are not cleaned up automatically.** Schedule `DELETE FROM refresh_tokens WHERE expires_at < now() - interval '30 days'`.

## License

MIT; see [LICENSE](LICENSE). Changes: [CHANGELOG.md](CHANGELOG.md).
