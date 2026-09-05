"""Integration tests for archiving a group.

Archiving is per member, so the interesting assertions are about two accounts disagreeing about
the same group. The rules themselves are driven locally by
tests/unit/service/test_archive_groups.py, since make integration needs a Postgres this
project's development machine does not have.
"""


def _register(client, email: str, name: str = "Otro") -> dict:
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


def _create_group(client, headers, name="Casa") -> int:
    response = client.post("/api/v1/groups/", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _group_ids(client, headers, archived: bool = False) -> list:
    suffix = "?archived=true" if archived else ""
    response = client.get(f"/api/v1/groups/{suffix}", headers=headers)
    assert response.status_code == 200, response.text
    return [g["id"] for g in response.json()["data"]]


def test_archiving_removes_it_from_my_list(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    response = client.post(f"/api/v1/groups/{group_id}/archive", headers=auth_headers)

    assert response.status_code == 204, response.text
    assert group_id not in _group_ids(client, auth_headers)
    assert group_id in _group_ids(client, auth_headers, archived=True)


def test_unarchiving_brings_it_back(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    client.post(f"/api/v1/groups/{group_id}/archive", headers=auth_headers)

    response = client.post(f"/api/v1/groups/{group_id}/unarchive", headers=auth_headers)

    assert response.status_code == 204, response.text
    assert group_id in _group_ids(client, auth_headers)
    assert group_id not in _group_ids(client, auth_headers, archived=True)


def test_archiving_does_not_affect_another_member(client, auth_headers):
    """The property the whole design rests on: two accounts, two different views."""
    group_id = _create_group(client, auth_headers)
    other = _register(client, "otro@example.com")
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    assert members  # the creator is a member
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Otro", "channel": "email", "contact": "otro@example.com"},
        headers=auth_headers,
    )

    client.post(f"/api/v1/groups/{group_id}/archive", headers=auth_headers)

    # The archiver no longer sees it; the other member is untouched.
    assert group_id not in _group_ids(client, auth_headers)
    assert group_id not in _group_ids(client, other, archived=True)


def test_archiving_is_blocked_with_an_outstanding_balance(client, auth_headers):
    """Putting a group away must not hide a debt."""
    group_id = _create_group(client, auth_headers)
    me = client.get("/api/v1/members/me", headers=auth_headers).json()["data"]["id"]
    client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)
    client.post(
        f"/api/v1/groups/{group_id}/expenses/",
        json={
            "description": "Luz",
            "amount": 100.0,
            "date": "2026-05-10",
            "category": {"name": "servicios"},
            "payerId": me,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )

    response = client.post(f"/api/v1/groups/{group_id}/archive", headers=auth_headers)

    assert response.status_code == 400
    assert group_id in _group_ids(client, auth_headers)


def test_archive_requires_authentication(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    assert client.post(f"/api/v1/groups/{group_id}/archive").status_code == 401
    assert client.post(f"/api/v1/groups/{group_id}/unarchive").status_code == 401


def test_default_list_is_unchanged_for_clients_that_do_not_ask(client, auth_headers):
    """Existing callers that never pass `archived` keep today's response."""
    group_id = _create_group(client, auth_headers)

    assert group_id in _group_ids(client, auth_headers)
