"""Joining a group by link with an existing account.

Covers the four caller/claim combinations at the HTTP layer. The merge rules themselves are
driven locally by tests/unit/service/test_member_merge.py, since make integration needs a
Postgres this project's development machine does not have.
"""


def _register(client, email: str, name: str = "Otro") -> dict:
    """Create a second account and return its auth header."""
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "telephone": "5411000000", "password": "secret123"},
    )
    token = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _group_with_link(client, auth_headers, name="Asado") -> tuple[int, str]:
    group_id = client.post("/api/v1/groups/", json={"name": name}, headers=auth_headers).json()["data"]["id"]
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]
    return group_id, token


def _add_ghost(client, auth_headers, group_id: int, name="Guada") -> int:
    response = client.post(f"/api/v1/groups/{group_id}/members", json={"name": name}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]["memberId"]


def test_authenticated_join_needs_no_credentials(client, auth_headers):
    """A logged-in user joins with just their JWT and an empty body."""
    group_id, token = _group_with_link(client, auth_headers)
    joiner = _register(client, "joiner@example.com")

    response = client.post(f"/api/v1/join/{token}", json={}, headers=joiner)

    assert response.status_code == 200, response.text
    names = [m["name"] for m in client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]]
    assert "Otro" in names


def test_authenticated_join_claiming_a_ghost_merges_it(client, auth_headers):
    """The ghost is absorbed: the group ends up with the account, not both rows."""
    group_id, token = _group_with_link(client, auth_headers)
    ghost_id = _add_ghost(client, auth_headers, group_id)
    joiner = _register(client, "guada@example.com", name="Guada")

    response = client.post(f"/api/v1/join/{token}", json={"claimMemberId": ghost_id}, headers=joiner)

    assert response.status_code == 200, response.text
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    ids = [m["memberId"] for m in members]
    assert ghost_id not in ids, "the ghost must be absorbed, not left alongside the account"


def test_anonymous_join_without_credentials_is_rejected(client, auth_headers):
    """Without a JWT the body must carry name, email and password."""
    _, token = _group_with_link(client, auth_headers)

    response = client.post(f"/api/v1/join/{token}", json={})

    assert response.status_code == 400


def test_anonymous_join_with_credentials_still_works(client, auth_headers):
    """The pre-existing registration path is untouched."""
    group_id, token = _group_with_link(client, auth_headers)

    response = client.post(
        f"/api/v1/join/{token}",
        json={"name": "Nuevo", "email": "nuevo@example.com", "password": "secret123"},
    )

    assert response.status_code == 200, response.text
    names = [m["name"] for m in client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]]
    assert "Nuevo" in names


def test_resolve_reports_already_member_for_an_authenticated_caller(client, auth_headers):
    """The creator opening their own link is told they are already in."""
    _, token = _group_with_link(client, auth_headers)

    response = client.get(f"/api/v1/join/resolve/{token}", headers=auth_headers)

    assert response.json()["data"]["alreadyMember"] is True


def test_resolve_without_a_jwt_reports_not_already_member(client, auth_headers):
    """Anonymous resolve stays public and defaults to False."""
    _, token = _group_with_link(client, auth_headers)

    response = client.get(f"/api/v1/join/resolve/{token}")

    assert response.status_code == 200
    assert response.json()["data"]["alreadyMember"] is False


def test_cannot_claim_an_invited_stub_with_an_existing_account(client, auth_headers):
    """The contactless precondition holds on the authenticated path too."""
    group_id, token = _group_with_link(client, auth_headers)
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Ivi", "channel": "email", "contact": "ivi@example.com"},
        headers=auth_headers,
    )
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    invited_id = [m for m in members if m["name"] == "Ivi"][0]["memberId"]
    joiner = _register(client, "attacker@example.com")

    response = client.post(f"/api/v1/join/{token}", json={"claimMemberId": invited_id}, headers=joiner)

    assert response.status_code == 400
