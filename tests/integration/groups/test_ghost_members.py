"""Integration tests for name-only ("ghost") group members and claiming one on join.

These cover status codes, auth and the wire shape. The claim *rules* are driven locally by
tests/unit/service/test_ghost_member_claiming.py, since make integration needs a Postgres
this project's development machine does not have.
"""


def _make_group(client, auth_headers, name="Asado") -> int:
    response = client.post("/api/v1/groups/", json={"name": name}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _add_ghost(client, auth_headers, group_id: int, name="Guada") -> int:
    response = client.post(f"/api/v1/groups/{group_id}/members", json={"name": name}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]["memberId"]


def _join_token(client, auth_headers, group_id: int) -> str:
    response = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


# ---------------------------------------------------------------------------
# Adding a member by name
# ---------------------------------------------------------------------------


def test_add_member_with_only_a_name(client, auth_headers):
    """A ghost member needs no email and no phone."""
    group_id = _make_group(client, auth_headers)

    response = client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)

    assert response.status_code == 201
    member = response.json()["data"]
    assert member["name"] == "Guada"
    assert member["email"] is None
    assert member["telephone"] is None
    assert member["isStub"] is True


def test_ghost_member_appears_in_the_group_member_list(client, auth_headers):
    """The new member is a real group member, not a pending invitation."""
    group_id = _make_group(client, auth_headers)
    _add_ghost(client, auth_headers, group_id)

    response = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers)

    assert "Guada" in [m["name"] for m in response.json()["data"]]


def test_adding_a_member_requires_belonging_to_the_group(client, auth_headers):
    """A caller outside the group cannot add members to it."""
    response = client.post("/api/v1/groups/99999/members", json={"name": "Guada"}, headers=auth_headers)

    assert response.status_code in (400, 403, 404)


def test_adding_a_member_requires_a_non_empty_name(client, auth_headers):
    """An empty name is rejected by the schema."""
    group_id = _make_group(client, auth_headers)

    response = client.post(f"/api/v1/groups/{group_id}/members", json={"name": ""}, headers=auth_headers)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Claiming on join
# ---------------------------------------------------------------------------


def test_resolve_join_token_lists_only_contactless_stubs(client, auth_headers):
    """Ghost members are claimable; invited stubs are not."""
    group_id = _make_group(client, auth_headers)
    _add_ghost(client, auth_headers, group_id)
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Ivi", "channel": "email", "contact": "ivi@example.com"},
        headers=auth_headers,
    )
    token = _join_token(client, auth_headers, group_id)

    response = client.get(f"/api/v1/join/resolve/{token}")

    claimable = response.json()["data"]["claimableMembers"]
    assert [m["name"] for m in claimable] == ["Guada"]
    assert all("memberId" in m for m in claimable)


def test_joining_while_claiming_keeps_the_existing_member_id(client, auth_headers):
    """Claiming preserves the row, so expenses already attributed to it follow along."""
    group_id = _make_group(client, auth_headers)
    ghost_id = _add_ghost(client, auth_headers, group_id)
    token = _join_token(client, auth_headers, group_id)

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Guada",
            "email": "guada@example.com",
            "password": "secret123",
            "claimMemberId": ghost_id,
        },
    )

    assert response.status_code == 200, response.text
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    claimed = [m for m in members if m["memberId"] == ghost_id]
    assert len(claimed) == 1, "claiming must not create a second member"
    assert claimed[0]["email"] == "guada@example.com"
    assert claimed[0]["isStub"] is False


def test_cannot_claim_a_member_that_has_contact_details(client, auth_headers):
    """An invited stub is addressed to a specific person and is never claimable."""
    group_id = _make_group(client, auth_headers)
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Ivi", "channel": "email", "contact": "ivi@example.com"},
        headers=auth_headers,
    )
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    invited_id = [m for m in members if m["name"] == "Ivi"][0]["memberId"]
    token = _join_token(client, auth_headers, group_id)

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Attacker",
            "email": "attacker@example.com",
            "password": "secret123",
            "claimMemberId": invited_id,
        },
    )

    assert response.status_code == 400


def test_cannot_claim_a_member_from_another_group(client, auth_headers):
    """The claimed member must belong to the group the token points at."""
    other_group = _make_group(client, auth_headers, name="Otro")
    outsider_id = _add_ghost(client, auth_headers, other_group, name="Ajeno")
    group_id = _make_group(client, auth_headers)
    token = _join_token(client, auth_headers, group_id)

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Attacker",
            "email": "attacker2@example.com",
            "password": "secret123",
            "claimMemberId": outsider_id,
        },
    )

    assert response.status_code == 400


def test_joining_without_claiming_still_creates_a_new_member(client, auth_headers):
    """The existing path is untouched when claimMemberId is absent."""
    group_id = _make_group(client, auth_headers)
    token = _join_token(client, auth_headers, group_id)

    response = client.post(
        f"/api/v1/join/{token}",
        json={"name": "Nuevo", "email": "nuevo@example.com", "password": "secret123"},
    )

    assert response.status_code == 200, response.text
    names = [m["name"] for m in client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]]
    assert "Nuevo" in names
