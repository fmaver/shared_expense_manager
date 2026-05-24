"""Integration tests for group CRUD endpoints."""


def test_groups_requires_auth(client):
    r = client.get("/api/v1/groups/")
    assert r.status_code == 401


def test_create_group(client, auth_headers):
    r = client.post("/api/v1/groups/", json={"name": "Fran & Guada"}, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["name"] == "Fran & Guada"
    assert data["status"] == "active"
    assert len(data["members"]) == 1


def test_list_groups_returns_own_groups(client, auth_headers):
    client.post("/api/v1/groups/", json={"name": "Group A"}, headers=auth_headers)
    client.post("/api/v1/groups/", json={"name": "Group B"}, headers=auth_headers)

    r = client.get("/api/v1/groups/", headers=auth_headers)
    assert r.status_code == 200
    names = [g["name"] for g in r.json()["data"]]
    assert "Group A" in names
    assert "Group B" in names


def test_get_group_by_id(client, auth_headers, primary_group_id):
    r = client.get(f"/api/v1/groups/{primary_group_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == primary_group_id


def test_get_group_not_found(client, auth_headers):
    r = client.get("/api/v1/groups/99999", headers=auth_headers)
    assert r.status_code == 404


def test_update_group_name(client, auth_headers, primary_group_id):
    r = client.put(
        f"/api/v1/groups/{primary_group_id}",
        json={"name": "Renamed Group"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "Renamed Group"


def test_list_group_members(client, auth_headers, primary_group_id, primary_member_id):
    r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
    assert r.status_code == 200
    member_ids = [m["memberId"] for m in r.json()["data"]]
    assert primary_member_id in member_ids


def test_invite_member_by_email(client, auth_headers, primary_group_id):
    # Register a second member to invite
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Counterparty",
            "telephone": "5499966665555",
            "email": "counterparty@example.com",
            "password": "secret123",
        },
    )

    r = client.post(
        f"/api/v1/groups/{primary_group_id}/members/invite",
        json={"email": "counterparty@example.com"},
        headers=auth_headers,
    )
    assert r.status_code == 204

    members_r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
    emails = [m["email"] for m in members_r.json()["data"]]
    assert "counterparty@example.com" in emails


def test_invite_nonexistent_member_returns_400(client, auth_headers, primary_group_id):
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/members/invite",
        json={"email": "nobody@nowhere.com"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_leave_group(client, auth_headers, primary_group_id):
    r = client.delete(f"/api/v1/groups/{primary_group_id}/members/leave", headers=auth_headers)
    assert r.status_code == 204

    # Group no longer appears in the member's list
    groups_r = client.get("/api/v1/groups/", headers=auth_headers)
    ids = [g["id"] for g in groups_r.json()["data"]]
    assert primary_group_id not in ids


def _create_expense_with_two_members(client, auth_headers, group_id, payer_id):
    """Create a $100 equal-split expense so both members have a non-zero balance."""
    return client.post(
        f"/api/v1/groups/{group_id}/expenses/",
        json={
            "description": "shared dinner",
            "amount": 100.0,
            "date": "2026-05-01",
            "category": {"name": "comida"},
            "payerId": payer_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )


def test_leave_group_blocked_when_creditor(client, auth_headers, primary_group_id, primary_member_id):
    """Payer cannot leave while the month is unsettled (they are owed money)."""
    # Invite a second member so the equal split is non-trivial
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Counterparty",
            "telephone": "5499966665555",
            "email": "counterparty@example.com",
            "password": "secret123",
        },
    )
    client.post(
        f"/api/v1/groups/{primary_group_id}/members/invite",
        json={"email": "counterparty@example.com"},
        headers=auth_headers,
    )

    r = _create_expense_with_two_members(client, auth_headers, primary_group_id, primary_member_id)
    assert r.status_code == 201

    # Primary member paid — they have a positive (creditor) balance; leaving must be blocked
    r = client.delete(f"/api/v1/groups/{primary_group_id}/members/leave", headers=auth_headers)
    assert r.status_code == 400
    assert "balance" in r.json()["detail"].lower()


def test_leave_group_blocked_when_debtor(client, auth_headers, primary_group_id, primary_member_id):
    """Non-payer cannot leave while the month is unsettled (they owe money)."""
    # Register and authenticate a second member
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Counterparty",
            "telephone": "5499966665555",
            "email": "counterparty@example.com",
            "password": "secret123",
        },
    )
    secondary_token = client.post(
        "/api/v1/auth/token",
        data={"username": "counterparty@example.com", "password": "secret123"},
    ).json()["access_token"]
    secondary_headers = {"Authorization": f"Bearer {secondary_token}"}

    client.post(
        f"/api/v1/groups/{primary_group_id}/members/invite",
        json={"email": "counterparty@example.com"},
        headers=auth_headers,
    )

    r = _create_expense_with_two_members(client, auth_headers, primary_group_id, primary_member_id)
    assert r.status_code == 201

    # Secondary member owes money (debtor balance); leaving must be blocked
    r = client.delete(f"/api/v1/groups/{primary_group_id}/members/leave", headers=secondary_headers)
    assert r.status_code == 400
    assert "balance" in r.json()["detail"].lower()


def test_leave_group_allowed_after_settling(client, auth_headers, primary_group_id, primary_member_id):
    """Member can leave once the month is settled (balances resolved)."""
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Counterparty",
            "telephone": "5499966665555",
            "email": "counterparty@example.com",
            "password": "secret123",
        },
    )
    client.post(
        f"/api/v1/groups/{primary_group_id}/members/invite",
        json={"email": "counterparty@example.com"},
        headers=auth_headers,
    )

    _create_expense_with_two_members(client, auth_headers, primary_group_id, primary_member_id)

    # Settle the month — balances are now resolved
    client.post(f"/api/v1/groups/{primary_group_id}/shares/settle/2026/05", headers=auth_headers)

    r = client.delete(f"/api/v1/groups/{primary_group_id}/members/leave", headers=auth_headers)
    assert r.status_code == 204
