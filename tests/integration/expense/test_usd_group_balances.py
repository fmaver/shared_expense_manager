"""USD expenses in a group: balances, cuotas, recurring templates, settlement and /personal,
all in ARS at the blue rate. The rate is pinned so the numbers are exact."""

import datetime

import pytest

RATE = 1500.0
TODAY = datetime.date.today()


@pytest.fixture
def rate(monkeypatch):
    """Pin the blue rate; tests can set rate.value = None to simulate dolarapi being down."""

    class _Rate:
        value: float | None = RATE

    holder = _Rate()
    monkeypatch.setattr("template.service_layer.currency_service.get_blue_rate", lambda: holder.value)
    return holder


def _ghost(client, auth_headers, group_id) -> int:
    r = client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["memberId"]


def _add(client, auth_headers, group_id, payer_id, *, amount, split=None, when=TODAY, **extra):
    payload = {
        "description": "Hotel",
        "amount": amount,
        "date": when.isoformat(),
        "category": {"name": "viajes"},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": split or {"type": "equal"},
        "currency": "USD",
    }
    payload.update(extra)
    return client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=auth_headers)


def _balances(client, auth_headers, group_id, year, month) -> dict:
    r = client.get(f"/api/v1/groups/{group_id}/shares/{year}/{month:02d}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["balances"]


def test_usd_exact_split_balances_in_ars_and_personal_ledger_loads(  # pylint: disable=unused-argument
    client, auth_headers, primary_member_id, primary_group_id, rate
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    split = {"type": "exact", "amounts": {str(primary_member_id): 150.0, str(ghost): 50.0}}
    r = _add(client, auth_headers, primary_group_id, primary_member_id, amount=200.0, split=split)
    assert r.status_code == 201, r.text

    assert _balances(client, auth_headers, primary_group_id, TODAY.year, TODAY.month) == {
        str(primary_member_id): 75000.0,
        str(ghost): -75000.0,
    }

    r = client.get(f"/api/v1/personal/ledger/{TODAY.year}/{TODAY.month}", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["usdRate"] == RATE
    assert [s["shareAmount"] for s in data["mirroredShares"]] == [225000.0]
    assert data["groupBalances"][0]["netBalance"] == 75000.0


def test_usd_credit_cuotas_balance_in_ars(  # pylint: disable=unused-argument
    client, auth_headers, primary_member_id, primary_group_id, rate
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    r = _add(
        client,
        auth_headers,
        primary_group_id,
        primary_member_id,
        amount=300.0,
        paymentType="credit",
        installments=3,
    )
    assert r.status_code == 201, r.text

    first = datetime.date(TODAY.year + TODAY.month // 12, TODAY.month % 12 + 1, 1)
    balances = _balances(client, auth_headers, primary_group_id, first.year, first.month)
    # US$100 per cuota, split equally → each side US$50 = $75,000
    assert balances == {str(primary_member_id): 75000.0, str(ghost): -75000.0}


def test_usd_recurring_template_materializes_in_ars(  # pylint: disable=unused-argument
    client, auth_headers, primary_member_id, primary_group_id, rate
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/recurring/",
        json={
            "description": "Netflix",
            "amount": 20.0,
            "category": "servicios",
            "payerId": primary_member_id,
            "paymentType": "debit",
            "splitStrategy": {"type": "equal"},
            "startYear": TODAY.year,
            "startMonth": TODAY.month,
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    # an ARS anchor so the month exists; GET materializes the template
    r = _add(client, auth_headers, primary_group_id, primary_member_id, amount=1000.0, currency="ARS")
    assert r.status_code == 201, r.text

    balances = _balances(client, auth_headers, primary_group_id, TODAY.year, TODAY.month)
    # ARS 1000 → ±500; US$20 → ±US$10 = ±15,000
    assert balances == {str(primary_member_id): 15500.0, str(ghost): -15500.0}


def test_settle_usd_month_transfers_ars(  # pylint: disable=unused-argument
    client, auth_headers, primary_member_id, primary_group_id, rate
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    assert _add(client, auth_headers, primary_group_id, primary_member_id, amount=200.0).status_code == 201

    r = client.post(
        f"/api/v1/groups/{primary_group_id}/shares/settle/{TODAY.year}/{TODAY.month:02d}", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/{TODAY.year}/{TODAY.month:02d}", headers=auth_headers)
    balancing = [e for e in r.json()["data"]["expenses"] if e["category"] == "balance"]
    assert [(e["payerId"], e["amount"], e["currency"]) for e in balancing] == [(ghost, 150000.0, "ARS")]


def test_settle_usd_month_without_rate_is_refused(client, auth_headers, primary_member_id, primary_group_id, rate):
    _ghost(client, auth_headers, primary_group_id)
    assert _add(client, auth_headers, primary_group_id, primary_member_id, amount=200.0).status_code == 201

    rate.value = None
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/shares/settle/{TODAY.year}/{TODAY.month:02d}", headers=auth_headers
    )
    assert r.status_code == 400, r.text
    assert "cotización" in r.json()["detail"]

    rate.value = RATE
    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/{TODAY.year}/{TODAY.month:02d}", headers=auth_headers)
    assert r.json()["data"]["isSettled"] is False


def test_settle_all_without_rate_settles_nothing(client, auth_headers, primary_member_id, rate):
    r = client.post("/api/v1/groups/", json={"name": "Viaje", "groupType": "one_time"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    group_id = r.json()["data"]["id"]
    _ghost(client, auth_headers, group_id)
    last_month = TODAY.replace(day=1) - datetime.timedelta(days=1)
    # an ARS month first (would settle fine on its own) and a USD month after it
    r = _add(client, auth_headers, group_id, primary_member_id, amount=1000.0, currency="ARS", when=last_month)
    assert r.status_code == 201, r.text
    assert _add(client, auth_headers, group_id, primary_member_id, amount=200.0).status_code == 201

    rate.value = None
    r = client.post(f"/api/v1/groups/{group_id}/shares/settle-all", headers=auth_headers)
    assert r.status_code == 400, r.text

    rate.value = RATE
    r = client.get(f"/api/v1/groups/{group_id}/shares/all", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["isSettled"] is False
    assert not [e for e in r.json()["data"]["expenses"] if e["category"] == "balance"]
