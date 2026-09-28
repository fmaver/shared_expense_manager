"""Integration tests for GET /groups/{id}/shares/unsettled."""

from datetime import date


def _expense(payer_id, when: date, amount=1000.0):
    return {
        "description": "super",
        "amount": amount,
        "date": when.isoformat(),
        "category": {"name": "comida"},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }


def _add_member(client, auth_headers, group_id):
    r = client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text


def _months_ago(n: int) -> date:
    today = date.today()
    total = today.year * 12 + (today.month - 1) - n
    return date(total // 12, total % 12 + 1, 10)


def test_unsettled_lists_past_month_with_balance(client, auth_headers, primary_member_id, primary_group_id):
    _add_member(client, auth_headers, primary_group_id)
    past = _months_ago(2)
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/", json=_expense(primary_member_id, past), headers=auth_headers
    )
    assert r.status_code == 201, r.text
    # current month also has a balance, and must not be listed
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense(primary_member_id, date.today()),
        headers=auth_headers,
    )

    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == [{"year": past.year, "month": past.month}]


def test_unsettled_skips_settled_month(client, auth_headers, primary_member_id, primary_group_id):
    _add_member(client, auth_headers, primary_group_id)
    past = _months_ago(1)
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/", json=_expense(primary_member_id, past), headers=auth_headers
    )
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/shares/settle/{past.year}/{past.month:02d}", headers=auth_headers
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers=auth_headers)
    assert r.json()["data"] == []


def test_unsettled_requires_membership(client, auth_headers, primary_group_id):
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Otro", "telephone": "5499911112222", "email": "otro@example.com", "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    token = client.post("/api/v1/auth/token", data={"username": "otro@example.com", "password": "secret123"}).json()[
        "access_token"
    ]

    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
