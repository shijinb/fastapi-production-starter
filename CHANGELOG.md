# Changelog

## [1.1.0] – 2026-10-25

### Fixed
- Concurrent refreshes with the same refresh token (parallel page loads, prefetches) no longer log the user out. A token rotated within `REFRESH_REUSE_GRACE_SECONDS` (default 10) may be reused while its family is active. Found by the end-to-end tests of saas-admin-dashboard.
- Text log format (`LOG_JSON=false`) now prints request fields (method, path, status, duration).

### Added
- Migration 0002: `refresh_tokens.revoke_reason` (`rotated`, `logout`, `reuse`, `deactivated`); grace reuse only applies to rotated tokens.

## [1.0.0] – 2026-10-25

First release.

- Auth: registration with organization, login, Argon2id, JWT access tokens, refresh-token rotation with reuse detection, logout.
- Multi-tenancy with service-layer scoping; roles owner/admin/member.
- Customers resource with search, filters, sorting, pagination and stats; audit log.
- Problem-details errors, JSON logs with request IDs, health and readiness probes.
- Alembic migrations, Docker image (non-root, health check), docker-compose, seed script, GitHub Actions CI with PostgreSQL and a Docker smoke test.
