"""Integration tests for expense CRUD endpoints."""

import json

import pytest


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


# ── Notification recipient scoping ────────────────────────────────────────────


def _capture_wpp_recipients(monkeypatch) -> list:
    """Patch the WhatsApp send seam and record every recipient phone number."""
    recipients: list = []

    def _fake_send(data):
        recipients.append(json.loads(data).get("to"))
        return {"detail": "mensaje enviado", "status_code": 200}

    monkeypatch.setattr(
        "template.service_layer.notification_service.enviar_mensaje_whatsapp",
        _fake_send,
    )
    return recipients


def _register_whatsapp_member(client, name, email, telephone) -> dict:
    """Register a member with WhatsApp notifications enabled; return their auth headers."""
    r = client.post(
        "/api/v1/auth/register",
        json={"name": name, "telephone": telephone, "email": email, "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    token = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": "secret123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    patched = client.patch(
        "/api/v1/members/me",
        json={"notificationPreference": "WHATSAPP"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    return headers


def test_expense_notification_not_sent_to_non_group_members(
    client, auth_headers, primary_member_id, primary_group_id, monkeypatch
):
    """Regression: a member who is NOT in the expense's group must never be notified.

    Reproduces the bug where the expense router notified every member in the whole
    system (MemberRepository.list()) instead of only the expense's group members.
    """
    outsider_phone = "5491133334444"
    _register_whatsapp_member(client, "Outsider", "outsider@example.com", outsider_phone)

    recipients = _capture_wpp_recipients(monkeypatch)

    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    assert (
        outsider_phone not in recipients
    ), f"Outsider (not a member of the group) was notified: recipients={recipients}"


# ── Similar expense endpoint ──────────────────────────────────────────────────


def _create_expense(
    client, auth_headers, group_id, member_id, description="supermercado", amount=1500.0, dt="2026-05-15"
):
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


def _create_credit_expense(
    client,
    auth_headers,
    group_id,
    member_id,
    description="helado credito",
    total_amount=12150.0,
    installments=1,
    dt="2026-09-27",
    currency="ARS",
):
    """Create a credit expense and return the parent (installment_no=1) row.

    Mirrors what the front sends: `amount` is the full purchase total — the backend splits it
    across `installments` and files the parent a month ahead of `dt` (see
    `ExpenseManager._handle_credit_expense`).
    """
    payload = {
        "description": description,
        "amount": total_amount,
        "date": dt,
        "category": {"name": "comida"},
        "payerId": member_id,
        "paymentType": "credit",
        "installments": installments,
        "currency": currency,
        "splitStrategy": {"type": "equal"},
    }
    r = client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    return r.json()["data"]


def _get_similar(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    client, auth_headers, group_id, amount, description, dt="2026-05-15", year=2026, month=5, currency="ARS"
):
    return client.get(
        f"/api/v1/groups/{group_id}/expenses/similar",
        params={
            "year": year,
            "month": month,
            "amount": amount,
            "description": description,
            "date": dt,
            "currency": currency,
        },
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


def test_similar_date_match_does_not_depend_on_requested_month(
    client, auth_headers, primary_member_id, primary_group_id
):
    """A credit expense is filed a month ahead of its own date (see repositories.py's
    find_similar_expenses docstring), so the date+amount signal must match regardless of which
    year/month the caller passes — otherwise a credit purchase's real duplicate is missed just
    because the front computes year/month from the (unshifted) expense date."""
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "unrelated description", year=2026, month=4)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_similar_no_match_different_group(client, auth_headers, primary_member_id, primary_group_id):
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0)
    r2 = client.post("/api/v1/groups/", json={"name": "Other Group"}, headers=auth_headers)
    other_group_id = r2.json()["data"]["id"]
    r = _get_similar(client, auth_headers, other_group_id, 1500.0, "supermercado")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_similar_matches_in_personal_group_by_amount_and_date(client, auth_headers, primary_member_id):
    """The personal group is a group like any other: same amount + same date must still warn.

    Regression test for a report that the "¿no lo cargaste ya?" warning only worked for regular
    groups. The repository query itself never special-cased group_type, but there was no test
    covering the personal group specifically — this closes that gap.
    """
    personal_group_id = client.get("/api/v1/personal/group", headers=auth_headers).json()["data"]["id"]
    _create_expense(
        client, auth_headers, personal_group_id, primary_member_id, "Helado con fran", 12150.0, "2026-09-27"
    )
    r = _get_similar(
        client, auth_headers, personal_group_id, 12150.0, "Helado perlatto", dt="2026-09-27", year=2026, month=9
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["description"] == "Helado con fran"


def test_similar_matches_credit_one_installment_in_personal_group(client, auth_headers, primary_member_id):
    """The owner's exact repro: a personal CREDIT expense (1 cuota) dated Sept 27 is filed in the
    October monthly share — querying with Sept's year/month (what the front sends, since it
    derives year/month from the expense's own date) must still find it."""
    personal_group_id = client.get("/api/v1/personal/group", headers=auth_headers).json()["data"]["id"]
    _create_credit_expense(
        client, auth_headers, personal_group_id, primary_member_id, "Helado credito", 12150.0, 1, "2026-09-27"
    )
    r = _get_similar(
        client, auth_headers, personal_group_id, 12150.0, "Helado perlatto", dt="2026-09-27", year=2026, month=9
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["description"] == "Helado credito (1/1)"


def test_similar_matches_credit_multi_installment_by_purchase_total(client, auth_headers, primary_member_id):
    """A 3-cuota credit purchase stores amount/3 per row — the match must reconstruct the full
    purchase total (amount * installments) before comparing, not the per-installment share."""
    personal_group_id = client.get("/api/v1/personal/group", headers=auth_headers).json()["data"]["id"]
    _create_credit_expense(
        client, auth_headers, personal_group_id, primary_member_id, "Heladera", 30000.0, 3, "2026-09-27"
    )
    r = _get_similar(
        client, auth_headers, personal_group_id, 30000.0, "Heladera otra vez", dt="2026-09-27", year=2026, month=9
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["amount"] == pytest.approx(10000.0)  # per-installment share, not the 30000 purchase total


def test_similar_matches_credit_one_installment_in_a_regular_group(
    client, auth_headers, primary_member_id, primary_group_id
):
    """Group-side equivalent of the personal-group credit repro — the matcher is shared by both."""
    _create_credit_expense(
        client, auth_headers, primary_group_id, primary_member_id, "Heladera grupo", 12150.0, 1, "2026-09-27"
    )
    r = _get_similar(
        client, auth_headers, primary_group_id, 12150.0, "Heladera otra", dt="2026-09-27", year=2026, month=9
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_similar_no_match_different_currency(client, auth_headers, primary_member_id, primary_group_id):
    """Same amount, same date, different currency is not a duplicate."""
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "supermercado", 1500.0, "2026-05-15")
    r = _get_similar(client, auth_headers, primary_group_id, 1500.0, "supermercado", dt="2026-05-15", currency="USD")
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
    # All 3 rows (parent + 2 children) share the purchase's original date ("2026-05-01") — only
    # the parent (installment_no=1) must come back, matched by the full purchase total (3000),
    # not the 1000 stored on each row.
    r = _get_similar(
        client, auth_headers, primary_group_id, 3000.0, "unrelated description", dt="2026-05-01", year=2026, month=5
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
    assert r.json()["data"][0]["installmentNo"] == 1
