"""Integration tests for the /personal/* router."""

import datetime


def test_personal_group_created_on_first_access(client, auth_headers):
    """GET /personal/group creates the personal group if it doesn't exist."""
    r = client.get("/api/v1/personal/group", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["groupType"] == "personal"
    assert data["name"] == "Personal"
    assert len(data["members"]) == 1


def test_personal_group_idempotent(client, auth_headers):
    """Calling GET /personal/group twice returns the same group."""
    r1 = client.get("/api/v1/personal/group", headers=auth_headers)
    r2 = client.get("/api/v1/personal/group", headers=auth_headers)
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]


def test_personal_group_not_in_groups_list(client, auth_headers):
    """Personal group does NOT appear in GET /groups/."""
    client.get("/api/v1/personal/group", headers=auth_headers)  # create it
    r = client.get("/api/v1/groups/", headers=auth_headers)
    types = [g["groupType"] for g in r.json()["data"]]
    assert "personal" not in types


def test_create_and_list_recurring_income(client, auth_headers):
    """Can create and list a recurring income template."""
    client.get("/api/v1/personal/group", headers=auth_headers)  # ensure personal group exists
    r = client.post(
        "/api/v1/personal/income/recurring",
        json={"label": "Sueldo", "amount": 1000.0},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["data"]["label"] == "Sueldo"
    assert r.json()["data"]["amount"] == 1000.0
    assert r.json()["data"]["active"] is True

    r2 = client.get("/api/v1/personal/income/recurring", headers=auth_headers)
    assert r2.status_code == 200
    assert len(r2.json()["data"]) == 1


def test_ledger_shows_income(client, auth_headers):
    """After creating a salary, GET /personal/ledger/{year}/{month} shows total_income."""
    today = datetime.date.today()
    client.post(
        "/api/v1/personal/income/recurring",
        json={"label": "Sueldo", "amount": 1500.0},
        headers=auth_headers,
    )
    r = client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["totalIncome"] == 1500.0
    assert data["projectedBalance"] == 1500.0
    assert data["pendingSettlementsTotal"] == 0.0


def test_ledger_mirrors_shared_expense_as_pending(client, auth_headers):
    """An expense in a shared 2-member group appears as a pending mirrored share."""
    today = datetime.date.today()

    # Register a second member
    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Bob",
            "telephone": "5499911112222",
            "email": "bob@example.com",
            "password": "secret123",
        },
    )
    assert r.status_code == 200

    # Create a shared group (owned by primary tester)
    r = client.post("/api/v1/groups/", json={"name": "Shared Group"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    group_id = r.json()["data"]["id"]

    # Get primary member id
    r = client.get("/api/v1/members/me", headers=auth_headers)
    primary_id = r.json()["data"]["id"]

    # Invite Bob by email (legacy auto-accept)
    r = client.post(
        f"/api/v1/groups/{group_id}/members/invite",
        json={"email": "bob@example.com"},
        headers=auth_headers,
    )
    assert r.status_code == 204, r.text

    # Add an expense: $200 split equally between 2 members
    r = client.post(
        f"/api/v1/groups/{group_id}/expenses/",
        json={
            "description": "Dinner",
            "amount": 200.0,
            "date": str(today),
            "category": {"name": "salidas"},
            "payerId": primary_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    # Check the ledger — should have a pending mirrored share of $100
    r = client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["totalSharesPending"] == 100.0
    assert data["totalSharesRealized"] == 0.0
    assert len(data["mirroredShares"]) == 1
    assert data["mirroredShares"][0]["status"] == "pending"
    assert data["mirroredShares"][0]["shareAmount"] == 100.0
    assert data["mirroredShares"][0]["sourceGroupId"] == group_id


def test_cannot_invite_to_personal_group(client, auth_headers):
    """Invitations to a personal group are rejected."""
    r = client.get("/api/v1/personal/group", headers=auth_headers)
    personal_group_id = r.json()["data"]["id"]

    r = client.post(
        f"/api/v1/groups/{personal_group_id}/invitations",
        json={"name": "Bob", "channel": "email", "contact": "bob@example.com"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_update_recurring_income(client, auth_headers):
    """PATCH updates label/amount and re-syncs current month."""
    today = datetime.date.today()
    r = client.post(
        "/api/v1/personal/income/recurring",
        json={"label": "Old Salary", "amount": 800.0},
        headers=auth_headers,
    )
    income_id = r.json()["data"]["id"]

    client.patch(
        f"/api/v1/personal/income/recurring/{income_id}",
        json={"amount": 1200.0},
        headers=auth_headers,
    )

    r = client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)
    assert r.json()["data"]["totalIncome"] == 1200.0


def test_variable_income_crud(client, auth_headers):
    """Can create, list, update, and delete variable income."""
    today = datetime.date.today()
    r = client.post(
        "/api/v1/personal/income/variable",
        json={
            "year": today.year,
            "month": today.month,
            "label": "Freelance",
            "amount": 300.0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    instance_id = r.json()["data"]["id"]

    r = client.get(
        f"/api/v1/personal/income/variable/{today.year}/{today.month}",
        headers=auth_headers,
    )
    assert len(r.json()["data"]) == 1

    client.patch(
        f"/api/v1/personal/income/variable/{instance_id}",
        json={"amount": 350.0},
        headers=auth_headers,
    )
    r = client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)
    assert r.json()["data"]["totalIncome"] == 350.0

    client.delete(
        f"/api/v1/personal/income/variable/{instance_id}",
        headers=auth_headers,
    )
    r = client.get(
        f"/api/v1/personal/income/variable/{today.year}/{today.month}",
        headers=auth_headers,
    )
    assert len(r.json()["data"]) == 0
