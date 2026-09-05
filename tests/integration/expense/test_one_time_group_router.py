"""Integration tests for one-time (occasion) groups.

Covers the HTTP surface: creating a group with a type, the credit rejection, and the two
aggregate endpoints. The aggregation logic itself is driven locally by
tests/unit/service/test_one_time_groups.py, since make integration needs a Postgres this
project's development machine does not have.
"""


def _create_group(client, auth_headers, group_type: str = "one_time", name: str = "Viaje") -> int:
    response = client.post(
        "/api/v1/groups/",
        json={"name": name, "groupType": group_type},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _me(client, auth_headers) -> int:
    return client.get("/api/v1/members/me", headers=auth_headers).json()["data"]["id"]


def _add_expense(client, auth_headers, group_id: int, *, payer_id: int, date: str, amount=100.0, **overrides):
    payload = {
        "description": "Cabaña",
        "amount": amount,
        "date": date,
        "category": {"name": "viajes"},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }
    payload.update(overrides)
    return client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=auth_headers)


# ---------------------------------------------------------------------------
# Creating a typed group
# ---------------------------------------------------------------------------


def test_create_a_one_time_group(client, auth_headers):
    """The type round-trips through the API."""
    group_id = _create_group(client, auth_headers)

    response = client.get(f"/api/v1/groups/{group_id}", headers=auth_headers)

    assert response.json()["data"]["groupType"] == "one_time"


def test_groups_default_to_regular(client, auth_headers):
    """Omitting groupType preserves today's behaviour for existing clients."""
    response = client.post("/api/v1/groups/", json={"name": "Casa"}, headers=auth_headers)

    assert response.status_code == 201
    assert response.json()["data"]["groupType"] == "regular"


def test_cannot_create_a_personal_group_through_the_api(client, auth_headers):
    """Personal groups are made only by get_or_create_personal_group."""
    response = client.post(
        "/api/v1/groups/",
        json={"name": "Mine", "groupType": "personal"},
        headers=auth_headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Credit is rejected
# ---------------------------------------------------------------------------


def test_credit_expense_is_rejected_in_a_one_time_group(client, auth_headers):
    """Enforced server-side, not just hidden in the form."""
    group_id = _create_group(client, auth_headers)
    me = _me(client, auth_headers)

    response = _add_expense(
        client, auth_headers, group_id, payer_id=me, date="2026-05-10", paymentType="credit", installments=3
    )

    assert response.status_code == 400


def test_credit_expense_is_allowed_in_a_regular_group(client, auth_headers):
    """The rule must not leak into ongoing groups."""
    group_id = _create_group(client, auth_headers, group_type="regular", name="Casa")
    me = _me(client, auth_headers)

    response = _add_expense(
        client, auth_headers, group_id, payer_id=me, date="2026-05-10", paymentType="credit", installments=3
    )

    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Aggregate endpoints
# ---------------------------------------------------------------------------


def test_aggregate_collapses_expenses_from_several_months(client, auth_headers):
    """Two months in, one list and one balance map out."""
    group_id = _create_group(client, auth_headers)
    me = _me(client, auth_headers)
    _add_expense(client, auth_headers, group_id, payer_id=me, date="2026-05-10", amount=100.0)
    _add_expense(client, auth_headers, group_id, payer_id=me, date="2026-06-10", amount=50.0)

    response = client.get(f"/api/v1/groups/{group_id}/shares/all", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data["expenses"]) == 2
    assert data["groupId"] == group_id
    assert data["isSettled"] is False


def test_aggregate_route_is_not_parsed_as_a_year(client, auth_headers):
    """/all must be matched before /{year}/{month}, or it 422s as an invalid year."""
    group_id = _create_group(client, auth_headers)

    response = client.get(f"/api/v1/groups/{group_id}/shares/all", headers=auth_headers)

    assert response.status_code == 200, response.text


def test_aggregate_on_an_empty_group_is_empty_not_an_error(client, auth_headers):
    """A freshly created occasion has nothing in it and must not 404 or 500."""
    group_id = _create_group(client, auth_headers)

    response = client.get(f"/api/v1/groups/{group_id}/shares/all", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["expenses"] == []
    assert data["balances"] == {}


def test_settle_all_closes_every_month(client, auth_headers):
    """One call settles the whole occasion, across both months."""
    group_id = _create_group(client, auth_headers)
    me = _me(client, auth_headers)
    _add_expense(client, auth_headers, group_id, payer_id=me, date="2026-05-10")
    _add_expense(client, auth_headers, group_id, payer_id=me, date="2026-06-10")

    response = client.post(f"/api/v1/groups/{group_id}/shares/settle-all", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["isSettled"] is True

    # And it stays settled when read back.
    after = client.get(f"/api/v1/groups/{group_id}/shares/all", headers=auth_headers)
    assert after.json()["data"]["isSettled"] is True


def test_aggregate_requires_authentication(client, auth_headers):
    """Both new routes sit behind the same auth as the rest of the shares router."""
    group_id = _create_group(client, auth_headers)

    assert client.get(f"/api/v1/groups/{group_id}/shares/all").status_code == 401
    assert client.post(f"/api/v1/groups/{group_id}/shares/settle-all").status_code == 401


def _recurring_payload(payer_id: int) -> dict:
    return {
        "description": "Internet",
        "amount": 500.0,
        "category": "servicios",
        "payerId": payer_id,
        "paymentType": "debit",
        "splitStrategy": {"type": "equal"},
        "startYear": 2026,
        "startMonth": 5,
    }


def test_recurring_expense_is_rejected_in_a_one_time_group(client, auth_headers):
    """"Repeats every month" is meaningless where there are no months, and the materializer
    would keep minting expenses into an occasion that already ended."""
    group_id = _create_group(client, auth_headers)
    me = _me(client, auth_headers)

    response = client.post(
        f"/api/v1/groups/{group_id}/expenses/recurring/",
        json=_recurring_payload(me),
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text


def test_recurring_expense_is_allowed_in_a_regular_group(client, auth_headers):
    """The rule is scoped to one-time groups and must not leak."""
    group_id = _create_group(client, auth_headers, group_type="regular", name="Casa")
    me = _me(client, auth_headers)

    response = client.post(
        f"/api/v1/groups/{group_id}/expenses/recurring/",
        json=_recurring_payload(me),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
