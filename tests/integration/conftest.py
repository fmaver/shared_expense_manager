"""Integration test fixtures — requires a live PostgreSQL instance."""

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from template.adapters.database import SessionLocal
from template.asgi import get_application
from template.dependencies import get_whatsapp_client
from tests.fakes.fake_whatsapp_client import FakeWhatsAppClient


@pytest.fixture(autouse=True)
def clean_tables():
    """Reset sequences and wipe transient rows around each test."""
    # Setup: advance sequences past the manually-seeded member IDs so that
    # new inserts don't collide with Fran (id=1) and Guadi (id=2).
    with SessionLocal() as session:
        for table, col in [("members", "id"), ("expenses", "id"), ("monthly_shares", "id")]:
            session.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                    f"COALESCE((SELECT MAX({col}) FROM {table}), 0) + 1, false)"
                )
            )
        session.commit()

    yield

    with SessionLocal() as session:
        session.execute(text("DELETE FROM processed_wpp_messages"))
        session.execute(text("DELETE FROM chat_sessions"))
        session.execute(text("DELETE FROM expenses"))
        session.execute(text("DELETE FROM monthly_shares"))
        session.execute(text("DELETE FROM members WHERE id NOT IN (1, 2)"))
        session.commit()


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
