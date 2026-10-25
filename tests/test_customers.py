from typing import Any

from httpx import AsyncClient

from tests.conftest import add_user, bearer, register

CUSTOMERS = [
    {"name": "Asha Rao", "email": "asha@northwind.example.com", "company": "Northwind", "status": "active", "lifetime_value": "1200.50"},
    {"name": "Ben Okafor", "email": "ben@contoso.example.com", "company": "Contoso", "status": "lead", "lifetime_value": "0"},
    {"name": "Chen Wei", "email": "chen@northwind.example.com", "company": "Northwind", "status": "churned", "lifetime_value": "300"},
    {"name": "Dana 100% Real", "email": "dana@fabrikam.example.com", "company": "Fabrikam", "status": "active", "lifetime_value": "75.25"},
]


async def seed(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    created = []
    for customer in CUSTOMERS:
        response = await client.post("/api/v1/customers", headers=headers, json=customer)
        assert response.status_code == 201, response.text
        created.append(response.json())
    return created


async def test_create_and_read_customer(client: AsyncClient, owner: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/customers", headers=owner, json={"name": "  Asha Rao ", "email": "Asha@Northwind.EXAMPLE.com", "lifetime_value": "10.10"}
    )
    assert response.status_code == 201
    customer = response.json()
    assert customer["name"] == "Asha Rao"  # whitespace stripped
    assert customer["email"] == "asha@northwind.example.com"  # e-mail normalised
    assert customer["status"] == "lead" and customer["lifetime_value"] == "10.10"

    fetched = await client.get(f"/api/v1/customers/{customer['id']}", headers=owner)
    assert fetched.json() == customer


async def test_duplicate_email_within_organization_is_a_conflict(client: AsyncClient, owner: dict[str, str]) -> None:
    await client.post("/api/v1/customers", headers=owner, json={"name": "A", "email": "a@x.example.com"})
    duplicate = await client.post("/api/v1/customers", headers=owner, json={"name": "B", "email": "A@x.example.com"})
    assert duplicate.status_code == 409


async def test_validation_rejects_negative_money_and_too_many_decimals(client: AsyncClient, owner: dict[str, str]) -> None:
    for value in ("-1", "1.234"):
        response = await client.post(
            "/api/v1/customers", headers=owner, json={"name": "A", "email": "a@x.example.com", "lifetime_value": value}
        )
        assert response.status_code == 422


async def test_search_filter_sort_and_paginate(client: AsyncClient, owner: dict[str, str]) -> None:
    await seed(client, owner)

    def names(response: Any) -> list[str]:
        return [c["name"] for c in response.json()["items"]]

    search = await client.get("/api/v1/customers", headers=owner, params={"q": "northwind", "sort": "name"})
    assert names(search) == ["Asha Rao", "Chen Wei"]

    by_status = await client.get("/api/v1/customers", headers=owner, params=[("status", "active"), ("status", "lead"), ("sort", "name")])
    assert names(by_status) == ["Asha Rao", "Ben Okafor", "Dana 100% Real"]

    by_value = await client.get("/api/v1/customers", headers=owner, params={"sort": "-lifetime_value"})
    assert names(by_value)[0] == "Asha Rao"

    rich = await client.get("/api/v1/customers", headers=owner, params={"min_lifetime_value": "100"})
    assert rich.json()["total"] == 2

    page = await client.get("/api/v1/customers", headers=owner, params={"sort": "name", "page": 2, "page_size": 3})
    assert page.json() | {"items": None} == {"items": None, "total": 4, "page": 2, "page_size": 3, "pages": 2}
    assert names(page) == ["Dana 100% Real"]


async def test_search_treats_like_wildcards_literally(client: AsyncClient, owner: dict[str, str]) -> None:
    await seed(client, owner)
    percent = await client.get("/api/v1/customers", headers=owner, params={"q": "100%"})
    assert [c["name"] for c in percent.json()["items"]] == ["Dana 100% Real"]
    underscore = await client.get("/api/v1/customers", headers=owner, params={"q": "_"})
    assert underscore.json()["total"] == 0


async def test_invalid_query_parameters(client: AsyncClient, owner: dict[str, str]) -> None:
    assert (await client.get("/api/v1/customers", headers=owner, params={"sort": "password"})).status_code == 422
    assert (await client.get("/api/v1/customers", headers=owner, params={"page_size": 1000})).status_code == 422
    assert (await client.get("/api/v1/customers", headers=owner, params={"status": "vip"})).status_code == 422


async def test_partial_update_changes_only_sent_fields(client: AsyncClient, owner: dict[str, str]) -> None:
    customer = (await seed(client, owner))[1]
    response = await client.patch(f"/api/v1/customers/{customer['id']}", headers=owner, json={"status": "active"})
    updated = response.json()
    assert updated["status"] == "active"
    assert updated["name"] == customer["name"] and updated["company"] == customer["company"]


async def test_stats(client: AsyncClient, owner: dict[str, str]) -> None:
    await seed(client, owner)
    stats = (await client.get("/api/v1/customers/stats", headers=owner)).json()
    assert stats == {
        "total": 4,
        "by_status": {"lead": 1, "active": 2, "churned": 1},
        "total_lifetime_value": "1575.75",
        "new_last_30_days": 4,
    }


async def test_members_cannot_delete_admins_can(client: AsyncClient, owner: dict[str, str]) -> None:
    customer = (await seed(client, owner))[0]
    member = await add_user(client, owner, "mia@acme.example.com")

    forbidden = await client.delete(f"/api/v1/customers/{customer['id']}", headers=member)
    assert forbidden.status_code == 403 and forbidden.json()["detail"] == "Requires the admin role or higher"

    assert (await client.delete(f"/api/v1/customers/{customer['id']}", headers=owner)).status_code == 204
    assert (await client.get(f"/api/v1/customers/{customer['id']}", headers=owner)).status_code == 404


async def test_owner_must_belong_to_the_same_organization(client: AsyncClient, owner: dict[str, str]) -> None:
    outsider = await register(client, email="owner@globex.example.com", org="Globex")
    outsider_id = (await client.get("/api/v1/auth/me", headers=bearer(outsider))).json()["id"]
    response = await client.post(
        "/api/v1/customers", headers=owner, json={"name": "A", "email": "a@x.example.com", "owner_id": outsider_id}
    )
    assert response.status_code == 404
