"""Integration tests for recurring group expense endpoints.

Uses a real PostgreSQL database (TEST_DATABASE_URL must be set).
Fixtures: client, auth_headers, primary_member_id, primary_group_id, clean_tables.
"""

import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.date.today()
YEAR = TODAY.year
MONTH = TODAY.month


def _recurring_payload(payer_id: int, start_year: int = YEAR, start_month: int = MONTH) -> dict:
    """Minimal valid payload for creating a recurring group expense template."""
    return {
        "description": "Internet",
        "amount": 500.0,
        "category": "servicios",
        "payerId": payer_id,
        "paymentType": "debit",
        "splitStrategy": {"type": "equal"},
        "startYear": start_year,
        "startMonth": start_month,
    }


def _create_recurring(client, auth_headers, group_id, payer_id, **kwargs) -> dict:
    """POST and return the created template data (raises on non-201)."""
    payload = _recurring_payload(payer_id, **kwargs)
    r = client.post(
        f"/api/v1/groups/{group_id}/expenses/recurring/",
        json=payload,
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _get_monthly_share(client, auth_headers, group_id, year, month) -> dict:
    """GET monthly share; returns (status_code, response_json)."""
    r = client.get(f"/api/v1/groups/{group_id}/shares/{year}/{month:02d}", headers=auth_headers)
    return r


# ---------------------------------------------------------------------------
# Test 1: Create a recurring expense template
# ---------------------------------------------------------------------------


def test_create_recurring_expense(client, auth_headers, primary_member_id, primary_group_id):
    """POST to /recurring/ returns 201 with the created template data."""
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/",
        json=_recurring_payload(primary_member_id),
        headers=auth_headers,
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert "id" in data
    assert data["description"] == "Internet"
    assert data["amount"] == 500.0
    assert data["groupId"] == primary_group_id
    assert data["active"] is True
    assert data["startYear"] == YEAR
    assert data["startMonth"] == MONTH


# ---------------------------------------------------------------------------
# Test 2: List recurring expenses
# ---------------------------------------------------------------------------


def test_list_recurring_expenses(client, auth_headers, primary_member_id, primary_group_id):
    """After creating a template, GET /recurring/ returns it in the list."""
    _create_recurring(client, auth_headers, primary_group_id, primary_member_id)

    r = client.get(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/",
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["description"] == "Internet"
    assert data[0]["amount"] == 500.0


# ---------------------------------------------------------------------------
# Test 3: Recurring expense materializes in monthly share
# ---------------------------------------------------------------------------


def test_recurring_expense_materializes_in_monthly_share(
    client, auth_headers, primary_member_id, primary_group_id
):
    """After creating a template starting this month, GET the monthly share materializes it."""
    template = _create_recurring(client, auth_headers, primary_group_id, primary_member_id)
    template_id = template["id"]

    # Also create a regular expense so the monthly share endpoint returns 200 (not 404)
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json={
            "description": "Anchor expense",
            "amount": 100.0,
            "date": str(TODAY),
            "category": {"name": "otros"},
            "payerId": primary_member_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )

    r = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r.status_code == 200, r.text
    expenses = r.json()["data"]["expenses"]

    descriptions = [e["description"] for e in expenses]
    assert "Internet" in descriptions, f"Recurring expense not found in {descriptions}"

    # Verify the materialized expense is tagged with the template id
    recurring_expenses = [e for e in expenses if e["description"] == "Internet"]
    assert len(recurring_expenses) == 1
    assert recurring_expenses[0]["recurringTemplateId"] == template_id


# ---------------------------------------------------------------------------
# Test 4: Update recurring expense affects future months (re-materializes)
# ---------------------------------------------------------------------------


def test_update_recurring_expense_affects_future_months(
    client, auth_headers, primary_member_id, primary_group_id
):
    """PATCH with a new amount and viewed_month=current month, then GET materializes
    with updated amount."""
    template = _create_recurring(client, auth_headers, primary_group_id, primary_member_id)
    template_id = template["id"]

    # Add a regular expense to make the share GET-able
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json={
            "description": "Anchor",
            "amount": 50.0,
            "date": str(TODAY),
            "category": {"name": "otros"},
            "payerId": primary_member_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )

    # Trigger first materialization
    r1 = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r1.status_code == 200, r1.text
    original_amounts = [
        e["amount"] for e in r1.json()["data"]["expenses"] if e["description"] == "Internet"
    ]
    assert original_amounts == [500.0]

    # PATCH the template amount and invalidate current month so it re-materializes
    r_patch = client.patch(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/{template_id}",
        json={"amount": 750.0},
        params={"viewed_year": YEAR, "viewed_month": MONTH},
        headers=auth_headers,
    )
    assert r_patch.status_code == 200, r_patch.text
    assert r_patch.json()["data"]["amount"] == 750.0

    # GET the share again — should now include the re-materialized expense at 750.0
    r2 = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r2.status_code == 200, r2.text
    updated_amounts = [
        e["amount"] for e in r2.json()["data"]["expenses"] if e["description"] == "Internet"
    ]
    assert updated_amounts == [750.0], f"Expected 750.0, got {updated_amounts}"


# ---------------------------------------------------------------------------
# Test 5: Delete deactivates template and cleans future instances
# ---------------------------------------------------------------------------


def test_delete_recurring_expense_deactivates_and_cleans_future(
    client, auth_headers, primary_member_id, primary_group_id
):
    """DELETE with viewed_month deactivates the template and removes future instances.

    After deletion the template should no longer appear in the list (active_only=True)
    and the next GET of the monthly share should not re-materialize a new expense for
    the recurring template.
    """
    template = _create_recurring(client, auth_headers, primary_group_id, primary_member_id)
    template_id = template["id"]

    # Add regular expense so the share is GET-able
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json={
            "description": "Anchor",
            "amount": 50.0,
            "date": str(TODAY),
            "category": {"name": "otros"},
            "payerId": primary_member_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )

    # Trigger first materialization (creates an instance record)
    _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)

    # DELETE the template (has_instances=True → soft-delete + remove instances from MONTH onwards)
    r_del = client.delete(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/{template_id}",
        params={"viewed_year": YEAR, "viewed_month": MONTH},
        headers=auth_headers,
    )
    assert r_del.status_code == 204, r_del.text

    # Template should no longer appear in the active list
    r_list = client.get(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/",
        headers=auth_headers,
    )
    assert r_list.status_code == 200
    ids = [t["id"] for t in r_list.json()["data"]]
    assert template_id not in ids, "Deactivated template should not appear in active list"

    # GET the monthly share again — the recurring expense should not re-appear
    # (materialization is skipped because the template is inactive)
    r_share = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r_share.status_code == 200
    internet_expenses = [
        e for e in r_share.json()["data"]["expenses"]
        if e.get("recurringTemplateId") == template_id
    ]
    assert len(internet_expenses) == 0, "Deactivated recurring expense should not re-materialize"


# ---------------------------------------------------------------------------
# Test 6: Settled month is skipped during materialization
# ---------------------------------------------------------------------------


def test_settled_month_is_skipped_during_materialization(
    client, auth_headers, primary_member_id, primary_group_id
):
    """Materialization is a no-op for a settled month — no error, no duplicate."""
    template = _create_recurring(client, auth_headers, primary_group_id, primary_member_id)

    # Create a regular expense so the share can be settled
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json={
            "description": "Groceries",
            "amount": 300.0,
            "date": str(TODAY),
            "category": {"name": "comida"},
            "payerId": primary_member_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )

    # Trigger first materialization before settling
    r1 = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r1.status_code == 200, r1.text
    expense_count_before = len(r1.json()["data"]["expenses"])

    # Settle the month
    r_settle = client.post(
        f"/api/v1/groups/{primary_group_id}/shares/settle/{YEAR}/{MONTH:02d}",
        headers=auth_headers,
    )
    assert r_settle.status_code == 200, r_settle.text
    assert r_settle.json()["data"]["isSettled"] is True

    # GET the settled monthly share — materialization should be skipped, no new recurring expense
    r2 = _get_monthly_share(client, auth_headers, primary_group_id, YEAR, MONTH)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["isSettled"] is True

    # Count recurring-tagged expenses; no duplicates should have been created
    recurring_expenses = [
        e for e in r2.json()["data"]["expenses"]
        if e.get("recurringTemplateId") == template["id"]
    ]
    assert len(recurring_expenses) <= 1, (
        f"Expected at most 1 recurring expense in settled month, found {len(recurring_expenses)}"
    )
