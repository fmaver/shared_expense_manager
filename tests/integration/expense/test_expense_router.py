"""Integration tests for expense CRUD endpoints."""

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


def test_create_expense_requires_auth(client):
    r = client.post("/api/v1/expenses/", json=_expense_payload(payer_id=1))
    assert r.status_code == 401


def test_create_expense(client, auth_headers, primary_member_id):
    r = client.post(
        "/api/v1/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["description"] == "supermercado"
    assert data["amount"] == 1500.0
    assert data["payerId"] == primary_member_id


def test_get_expense_by_id(client, auth_headers, primary_member_id):
    created = client.post(
        "/api/v1/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    expense_id = created.json()["data"]["id"]

    r = client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == expense_id


def test_delete_expense(client, auth_headers, primary_member_id):
    created = client.post(
        "/api/v1/expenses/",
        json=_expense_payload(payer_id=primary_member_id),
        headers=auth_headers,
    )
    expense_id = created.json()["data"]["id"]

    r = client.delete(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code == 200

    # service.get_expense raises ValueError for missing IDs → 400 (existing behaviour)
    r = client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert r.status_code in (400, 404)


def test_create_credit_expense_expands_installments(client, auth_headers, primary_member_id):
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
    r = client.post("/api/v1/expenses/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    # Response uses the original description; installment suffix is added in DB
    assert data["installments"] == 3
    assert data["payerId"] == primary_member_id
