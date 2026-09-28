"""Integration tests for GET /search/expenses."""

from datetime import date


def _expense(payer_id, description, amount=1000.0, when="2026-05-10", category="comida", **extra):
    payload = {
        "description": description,
        "amount": amount,
        "date": when,
        "category": {"name": category},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }
    payload.update(extra)
    return payload


def _post(client, headers, group_id, payload):
    r = client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _search(client, headers, q, group_id=None):
    params = {"q": q}
    if group_id is not None:
        params["groupId"] = group_id
    r = client.get("/api/v1/search/expenses", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _other_user(client):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Extraño", "telephone": "5499933334444", "email": "x@example.com", "password": "secret123"},
    )
    token = client.post("/api/v1/auth/token", data={"username": "x@example.com", "password": "secret123"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def test_matches_every_word_in_description(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Cena en el centro"))
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Cena en casa"))
    data = _search(client, auth_headers, "cena centro")
    assert [r["description"] for r in data["results"]] == ["Cena en el centro"]
    assert data["hasMore"] is False


def test_matches_without_accents(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Café con medialunas"))
    assert len(_search(client, auth_headers, "cafe")["results"]) == 1


def test_matches_payer_name(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Luz"))
    results = _search(client, auth_headers, "tester")["results"]  # the auth_headers member is "Tester"
    assert [r["description"] for r in results] == ["Luz"]
    assert results[0]["payerName"] == "Tester"


def test_matches_exact_amount_with_local_format(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Carnicería", amount=24000.0))
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Verdulería", amount=2400.0))
    assert [r["description"] for r in _search(client, auth_headers, "24.000")["results"]] == ["Carnicería"]


def test_wildcards_are_literal(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Supermercado"))
    assert _search(client, auth_headers, "%%")["results"] == []
    assert _search(client, auth_headers, "__")["results"] == []


def test_excludes_internal_categories(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Pago a Guada", category="prestamo"))
    assert _search(client, auth_headers, "pago")["results"] == []


def test_one_row_per_installment_with_period_and_state(client, auth_headers, primary_member_id, primary_group_id):
    _post(
        client,
        auth_headers,
        primary_group_id,
        _expense(primary_member_id, "Equipo ski", amount=3000.0, paymentType="credit", installments=3),
    )
    results = _search(client, auth_headers, "ski")["results"]
    assert len(results) == 3
    assert sorted(r["installmentNo"] for r in results) == [1, 2, 3]
    assert all(r["installments"] == 3 for r in results)
    assert all(r["periodSettled"] is False for r in results)
    assert len({(r["periodYear"], r["periodMonth"]) for r in results}) == 3


def test_never_returns_expenses_from_a_group_you_are_not_in(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Secreto"))
    stranger = _other_user(client)
    assert _search(client, stranger, "secreto")["results"] == []
    r = client.get("/api/v1/search/expenses", params={"q": "secreto", "groupId": primary_group_id}, headers=stranger)
    assert r.status_code == 403


def test_group_scope_limits_to_that_group(client, auth_headers, primary_member_id, primary_group_id):
    other = client.post("/api/v1/groups/", json={"name": "Viaje"}, headers=auth_headers).json()["data"]["id"]
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Nafta casa"))
    _post(client, auth_headers, other, _expense(primary_member_id, "Nafta viaje"))
    results = _search(client, auth_headers, "nafta", group_id=other)["results"]
    assert [r["description"] for r in results] == ["Nafta viaje"]
    assert results[0]["groupName"] == "Viaje"


def test_archived_group_still_searchable(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Heladera", amount=10.0))
    # settle so the member carries no balance and is allowed to archive
    client.post(f"/api/v1/groups/{primary_group_id}/shares/settle/2026/05", headers=auth_headers)
    r = client.post(f"/api/v1/groups/{primary_group_id}/archive", headers=auth_headers)
    assert r.status_code in (200, 204), r.text
    assert len(_search(client, auth_headers, "heladera")["results"]) == 1


def test_includes_personal_fixed_expenses_without_date(client, auth_headers):
    today = date.today()
    client.get("/api/v1/personal/group", headers=auth_headers)
    r = client.post(
        "/api/v1/personal/expenses/recurring",
        json={
            "label": "Prepaga",
            "amount": 50000.0,
            "categoryName": "salud",
            "startYear": today.year,
            "startMonth": today.month,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)  # materializes

    results = _search(client, auth_headers, "prepaga")["results"]
    assert len(results) == 1
    assert results[0]["kind"] == "recurring_personal"
    assert results[0]["date"] is None
    assert (results[0]["periodYear"], results[0]["periodMonth"]) == (today.year, today.month)
    assert results[0]["periodSettled"] is None


def test_caps_at_fifty_with_has_more(client, auth_headers, primary_member_id, primary_group_id):
    for i in range(51):
        _post(client, auth_headers, primary_group_id, _expense(primary_member_id, f"Kiosco {i}", amount=1.0 + i))
    data = _search(client, auth_headers, "kiosco")
    assert len(data["results"]) == 50
    assert data["hasMore"] is True


def test_too_short_query_returns_empty(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Agua"))
    assert _search(client, auth_headers, "a")["results"] == []
