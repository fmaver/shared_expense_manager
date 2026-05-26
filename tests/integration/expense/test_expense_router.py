"""Integration tests for expense CRUD endpoints."""


def _expense_payload(payer_id: int, description="supermercado", amount=1500.0):
    return {
        "description": description,
        "amount": amount,
        "date": "2026-05-01",
        "category": {"name": "comida"},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }


def test_create_expense_requires_auth(client, primary_group_id):
    r = client.post(f"/api/v1/groups/{primary_group_id}/expenses/", json=_expense_payload(payer_id=1))
    assert r.status_code == 401


def test_create_expense(client, auth_headers, primary_member_id, primary_group_id):
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["description"] == "supermercado"
    assert data["amount"] == 1500.0
    assert data["payerId"] == primary_member_id


def test_get_expense_by_id(client, auth_headers, primary_member_id, primary_group_id):
    created = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    expense_id = created.json()["data"]["id"]

    r = client.get(f"/api/v1/groups/{primary_group_id}/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == expense_id


def test_delete_expense(client, auth_headers, primary_member_id, primary_group_id):
    created = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    expense_id = created.json()["data"]["id"]

    r = client.delete(f"/api/v1/groups/{primary_group_id}/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code == 200

    # service.get_expense raises ValueError for missing IDs → 400 (existing behaviour)
    r = client.get(f"/api/v1/groups/{primary_group_id}/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code in (400, 404)


def test_create_credit_expense_expands_installments(client, auth_headers, primary_member_id, primary_group_id):
    payload = {
        "description": "electrodoméstico",
        "amount": 6000.0,
        "date": "2026-05-01",
        "category": {"name": "compras"},
        "payerId": primary_member_id,
        "paymentType": "credit",
        "installments": 3,
        "splitStrategy": {"type": "equal"},
    }
    r = client.post(f"/api/v1/groups/{primary_group_id}/expenses/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["installments"] == 3
    assert data["payerId"] == primary_member_id


# ── Similar expense endpoint ──────────────────────────────────────────────────

def _create_expense(client, auth_headers, group_id, member_id, description="supermercado", amount=1500.0, dt="2026-05-15"):
    payload = {
        "description": description,
        "amount": amount,
        "date": dt,
        "category": {"name": "comida"},
        "payerId": member_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }
    r = client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    return r.json()["data"]


def _get_similar(client, auth_headers, group_id, amount, description, dt="2026-05-15", year=2026, month=5):
    return client.get(
        f"/api/v1/groups/{group_id}/expenses/similar",
        params={"year": year, "month": month, "amount": amount, "description": description, "date": dt},
        headers=auth_headers,
    )


def test_similar_requires_auth(client, primary_group_id):
    r = client.get(
        f"/api/v1/groups/{primary_group_id}/expenses/similar",
        params={"year": 2026, "month": 5, "amount": 100, "description": "x", "date": "2026-05-01"},
    )
    assert r.status_code == 401


def test_similar_returns_empty_when_no_match(client, auth_headers, primary_member_id, primary_group_id):
    r = _get_similar(client, auth_headers, primary_group_id, 9999.0, "unique description xyz")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_similar_matches_by_amount_and_description(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "supermercado", dt="2026-05-20")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["description"] == "supermercado"
    assert data[0]["amount"] == 1500.0


def test_similar_description_match_is_case_insensitive(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "Supermercado", 1500.0)
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "SUPERMERCADO", dt="2026-05-20")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_similar_matches_by_amount_and_date(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "electricidad", 1500.0, "2026-05-15")
    # different description but same amount + same date → should match
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "agua", dt="2026-05-15")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_similar_no_match_different_amount(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r = _get_similar(client, auth_headers, primary_group_id, 999.0, "supermercado")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_similar_no_match_different_month(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "supermercado", year=2026, month=4)
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_similar_no_match_different_group(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r2 = client.post("/api/v1/groups/", json={"name": "Other Group"}, headers=auth_headers)
    other_group_id = r2.json()["data"]["id"]
    r = _get_similar(client, auth_headers, other_group_id, 1500.0, "supermercado")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_similar_skips_credit_installment_children(client, auth_headers, primary_member_id, primary_group_id):
    """Only the parent installment (installment_no=1) is returned, not child rows."""
    payload = {
        "description": "heladera",
        "amount": 3000.0,
        "date": "2026-05-01",
        "category": {"name": "comida"},
        "payerId": primary_member_id,
        "paymentType": "credit",
        "installments": 3,
        "splitStrategy": {"type": "equal"},
    }
    client.post(f"/api/v1/groups/{primary_group_id}/expenses/", json=payload, headers=auth_headers)
    # Installment 1 lands in June 2026; query for it
    r = _get_similar(client, auth_headers, primary_group_id, 1000.0, "heladera (1/3)", dt="2026-06-01", year=2026, month=6)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
    assert r.json()["data"][0]["installmentNo"] == 1
