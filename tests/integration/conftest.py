"""Integration test fixtures — requires a live PostgreSQL instance."""

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from template.adapters.database import SessionLocal
from template.asgi import get_application
from template.dependencies import get_whatsapp_client
from tests.fakes.fake_whatsapp_client import FakeWhatsAppClient


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """Bootstrap schema once per session via the app lifespan.

    With MEMBERS_BOOTSTRAP_JSON unset (the default in tests) the lifespan
    creates tables but seeds no members; each test registers the members it
    needs via the API.
    """
    app = get_application()
    with TestClient(app):  # lifespan: create_all only
        pass


def _wipe_tables(session) -> None:
    session.execute(text("DELETE FROM processed_wpp_messages"))
    session.execute(text("DELETE FROM chat_sessions"))
    session.execute(text("DELETE FROM expenses"))
    session.execute(text("DELETE FROM monthly_shares"))
    session.execute(text("DELETE FROM group_memberships"))
    session.execute(text("DELETE FROM groups"))
    session.execute(text("DELETE FROM members"))
    session.commit()


@pytest.fixture(autouse=True)
def clean_tables(_create_schema):  # pylint: disable=redefined-outer-name
    """Wipe all transient rows before and after each test."""
    with SessionLocal() as session:
        _wipe_tables(session)
    yield
    with SessionLocal() as session:
        _wipe_tables(session)


@pytest.fixture
def fake_wpp() -> FakeWhatsAppClient:
    """Fresh FakeWhatsAppClient per test."""
    return FakeWhatsAppClient()


@pytest.fixture
def client(fake_wpp: FakeWhatsAppClient):  # pylint: disable=redefined-outer-name
    """FastAPI TestClient with test DB and FakeWhatsAppClient injected."""
    app = get_application()
    app.dependency_overrides[get_whatsapp_client] = lambda: fake_wpp
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict:  # pylint: disable=redefined-outer-name
    """Register a test member and return JWT Authorization headers."""
    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Tester",
            "telephone": "5499988887777",
            "email": "tester@example.com",
            "password": "secret123",
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/v1/auth/token",
        data={"username": "tester@example.com", "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def primary_group_id(client: TestClient, auth_headers: dict) -> int:  # pylint: disable=redefined-outer-name
    """Create a group owned by the primary test member; return its id."""
    r = client.post("/api/v1/groups/", json={"name": "Test Group"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


@pytest.fixture
def primary_member_id(client: TestClient, auth_headers: dict) -> int:  # pylint: disable=redefined-outer-name
    """ID of the primary test member registered by auth_headers."""
    r = client.get("/api/v1/members/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


@pytest.fixture
def secondary_member_id(client: TestClient) -> int:  # pylint: disable=redefined-outer-name
    """Register a second member via the API; return its id."""
    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Counterparty",
            "telephone": "5499966665555",
            "email": "counterparty@example.com",
            "password": "secret123",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]
