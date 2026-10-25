"""Tenant isolation, role checks, audit trail and platform behaviour (health, errors, request IDs)."""

from httpx import AsyncClient

from tests.conftest import add_user, bearer, register


async def test_organizations_cannot_see_each_others_data(client: AsyncClient, owner: dict[str, str]) -> None:
    acme_customer = (
        await client.post("/api/v1/customers", headers=owner, json={"name": "Acme Client", "email": "c@acme.example.com"})
    ).json()
    globex = bearer(await register(client, email="owner@globex.example.com", org="Globex"))
    await client.post("/api/v1/customers", headers=globex, json={"name": "Globex Client", "email": "c@globex.example.com"})

    listed = (await client.get("/api/v1/customers", headers=globex)).json()
    assert [c["name"] for c in listed["items"]] == ["Globex Client"]

    # Direct access by ID is "not found", not "forbidden", so IDs from another tenant cannot be probed.
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"name": "Hacked"}} if method == "patch" else {}
        response = await getattr(client, method)(f"/api/v1/customers/{acme_customer['id']}", headers=globex, **kwargs)
        assert response.status_code == 404, method

    assert (await client.get(f"/api/v1/customers/{acme_customer['id']}", headers=owner)).json()["name"] == "Acme Client"
    assert (await client.get("/api/v1/customers/stats", headers=globex)).json()["total"] == 1
    assert [u["email"] for u in (await client.get("/api/v1/users", headers=globex)).json()["items"]] == ["owner@globex.example.com"]


async def test_same_customer_email_is_allowed_in_different_organizations(client: AsyncClient, owner: dict[str, str]) -> None:
    globex = bearer(await register(client, email="owner@globex.example.com", org="Globex"))
    for headers in (owner, globex):
        assert (
            await client.post("/api/v1/customers", headers=headers, json={"name": "Shared", "email": "same@x.example.com"})
        ).status_code == 201


async def test_role_rules_for_user_management(client: AsyncClient, owner: dict[str, str]) -> None:
    admin = await add_user(client, owner, "ada@acme.example.com", role="admin")
    member = await add_user(client, owner, "mia@acme.example.com")

    # Members cannot add users; admins can.
    payload = {"email": "new@acme.example.com", "full_name": "New", "password": "a very long password"}
    assert (await client.post("/api/v1/users", headers=member, json=payload)).status_code == 403
    assert (await client.post("/api/v1/users", headers=admin, json=payload)).status_code == 201

    # Nobody can create another owner through the API.
    assert (
        await client.post("/api/v1/users", headers=owner, json=payload | {"email": "o2@acme.example.com", "role": "owner"})
    ).status_code == 422

    users = {u["email"]: u["id"] for u in (await client.get("/api/v1/users", headers=owner)).json()["items"]}
    # The owner account cannot be changed, and admins cannot demote or disable themselves.
    assert (
        await client.patch(f"/api/v1/users/{users['owner@acme.example.com']}", headers=admin, json={"is_active": False})
    ).status_code == 403
    assert (await client.patch(f"/api/v1/users/{users['ada@acme.example.com']}", headers=admin, json={"role": "member"})).status_code == 403
    assert (await client.patch(f"/api/v1/users/{users['mia@acme.example.com']}", headers=admin, json={"role": "admin"})).json()[
        "role"
    ] == "admin"


async def test_audit_trail_records_changes_for_admins_only(client: AsyncClient, owner: dict[str, str]) -> None:
    customer = (await client.post("/api/v1/customers", headers=owner, json={"name": "Asha", "email": "a@x.example.com"})).json()
    await client.patch(f"/api/v1/customers/{customer['id']}", headers=owner, json={"status": "active", "name": "Asha"})
    await client.delete(f"/api/v1/customers/{customer['id']}", headers=owner)

    events = (await client.get("/api/v1/audit-events", headers=owner, params={"entity_id": customer["id"]})).json()["items"]
    assert [e["action"] for e in events] == ["customer.deleted", "customer.updated", "customer.created"]
    # Only fields whose value actually changed are recorded.
    assert events[1]["changes"] == {"status": {"from": "lead", "to": "active"}}
    assert all(e["request_id"] for e in events)

    member = await add_user(client, owner, "mia@acme.example.com")
    assert (await client.get("/api/v1/audit-events", headers=member)).status_code == 403


async def test_health_and_readiness(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).json() == {"status": "ok", "database": "ok"}


async def test_request_id_is_echoed_or_generated(client: AsyncClient) -> None:
    echoed = await client.get("/health", headers={"X-Request-ID": "lb-1234"})
    assert echoed.headers["x-request-id"] == "lb-1234"
    generated = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert len(generated.headers["x-request-id"]) == 32


async def test_errors_use_problem_details(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "req-1"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not found",
        "status": 404,
        "detail": "Not Found",
        "instance": "/api/v1/does-not-exist",
        "request_id": "req-1",
    }


async def test_openapi_documents_every_route(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert {"/api/v1/auth/register", "/api/v1/customers", "/api/v1/customers/{customer_id}", "/api/v1/audit-events", "/ready"} <= set(paths)
