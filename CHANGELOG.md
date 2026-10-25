# Changelog

## [1.0.0] – 2026-10-25

First release.

- Auth: registration with organization, login, Argon2id, JWT access tokens, refresh-token rotation with reuse detection, logout.
- Multi-tenancy with service-layer scoping; roles owner/admin/member.
- Customers resource with search, filters, sorting, pagination and stats; audit log.
- Problem-details errors, JSON logs with request IDs, health and readiness probes.
- Alembic migrations, Docker image (non-root, health check), docker-compose, seed script, GitHub Actions CI with PostgreSQL and a Docker smoke test.
