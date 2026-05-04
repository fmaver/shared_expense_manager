"""Integration tests for auth endpoints."""

import pytest

REGISTER_PAYLOAD = {
    "name": "Alice",
    "telephone": "5491100001111",
    "email": "alice@example.com",
    "password": "password123",
}


def test_register_creates_member(client):
    r = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["name"] == "Alice"


def test_register_duplicate_email_returns_400(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    r = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert r.status_code == 400


def test_login_returns_token(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    r = client.post(
        "/api/v1/auth/token",
        data={"username": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    r = client.post(
        "/api/v1/auth/token",
        data={"username": "alice@example.com", "password": "wrong"},
    )
    assert r.status_code == 401


def test_get_me_requires_auth(client):
    r = client.get("/api/v1/members/me")
    assert r.status_code == 401


def test_get_me_returns_current_member(client, auth_headers):
    r = client.get("/api/v1/members/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["email"] == "tester@example.com"
