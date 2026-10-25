from httpx import AsyncClient

from tests.conftest import add_user, bearer, register

PASSWORD = "correct horse battery"


async def test_register_returns_tokens_and_creates_owner(client: AsyncClient) -> None:
    tokens = await register(client)
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 15 * 60

    me = await client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "owner@acme.example.com" and body["role"] == "owner"
    assert body["organization"]["name"] == "Acme Ltd"
    assert body["organization"]["slug"].startswith("acme-ltd-")
    assert "password_hash" not in body


async def test_register_rejects_duplicate_email_case_insensitively(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/register",
        json={"organization_name": "Other", "full_name": "X", "email": "OWNER@acme.example.com", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"


async def test_register_validates_input(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"organization_name": "", "full_name": "X", "email": "not-an-email", "password": "short"}
    )
    assert response.status_code == 422
    fields = {tuple(error["location"])[-1] for error in response.json()["errors"]}
    assert fields == {"organization_name", "email", "password"}


async def test_login_success_and_failure_messages_do_not_reveal_accounts(client: AsyncClient) -> None:
    await register(client)
    ok = await client.post("/api/v1/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD})
    assert ok.status_code == 200

    wrong_password = await client.post("/api/v1/auth/login", json={"email": "owner@acme.example.com", "password": "nope"})
    unknown_user = await client.post("/api/v1/auth/login", json={"email": "nobody@acme.example.com", "password": "nope"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"] == "Incorrect e-mail or password"
    assert wrong_password.headers["www-authenticate"] == "Bearer"


async def test_protected_routes_require_a_valid_access_token(client: AsyncClient) -> None:
    tokens = await register(client)
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    # A refresh token is not accepted where an access token is required.
    refresh_as_access = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert refresh_as_access.status_code == 401
    assert refresh_as_access.json()["detail"] == "Expected a access token"


async def test_refresh_rotates_tokens(client: AsyncClient) -> None:
    first = await register(client)
    second = (await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})).json()
    assert second["refresh_token"] != first["refresh_token"]
    assert (await client.get("/api/v1/auth/me", headers=bearer(second))).status_code == 200


async def test_refresh_token_reuse_revokes_the_whole_session(client: AsyncClient) -> None:
    first = await register(client)
    second = (await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})).json()

    # The old token is presented again (e.g. it was stolen): rejected, and the new one stops working too.
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["detail"] == "Refresh token has already been used"

    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert after.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    tokens = await register(client)
    assert (await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


async def test_deactivated_user_loses_access_immediately(client: AsyncClient, owner: dict[str, str]) -> None:
    member = await add_user(client, owner, "mia@acme.example.com")
    users = (await client.get("/api/v1/users", headers=owner)).json()["items"]
    member_id = next(u["id"] for u in users if u["email"] == "mia@acme.example.com")

    assert (await client.patch(f"/api/v1/users/{member_id}", headers=owner, json={"is_active": False})).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=member)).status_code == 401
    login = await client.post("/api/v1/auth/login", json={"email": "mia@acme.example.com", "password": "another long password"})
    assert login.status_code == 401 and login.json()["detail"] == "This account is disabled"
