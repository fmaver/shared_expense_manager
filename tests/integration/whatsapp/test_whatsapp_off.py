"""The webhook with WhatsApp switched off: one notice per phone, then silence.

The webhook keeps answering 200 and keeps the idempotency insert (Meta retries otherwise), but
the chatbot does not run. The first message from a phone gets one plain-text reply pointing to
the app — free, because the person just wrote — and that is recorded in `chat_sessions` so no
later message from that phone gets anything.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from template.adapters.database import SessionLocal
from template.domain.models.enums import NotificationType
from template.service_layer.whatsapp_switch import WHATSAPP_OFF_NOTICE_STATE

PHONE = "5499900001111"  # as Meta sends it: 549…
STORED_PHONE = "5499900001111"[:2] + "5499900001111"[3:]  # replace_start strips the 9


@pytest.fixture(name="_whatsapp_switch", autouse=True)
def _switch_off(monkeypatch):
    """Overrides the directory-wide fixture that turns the switch on: this file tests it off."""
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "https://app.jirens.test")


def _payload(message_id: str, body: str = "hola") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {"value": {"messages": [{"from": PHONE, "id": message_id, "type": "text", "text": {"body": body}}]}}
                ]
            }
        ]
    }


def _session_estado():
    with SessionLocal() as db:
        return db.execute(
            text("SELECT estado FROM chat_sessions WHERE telephone = :t"), {"t": STORED_PHONE}
        ).scalar_one_or_none()


def test_first_message_gets_exactly_one_notice(client, fake_wpp):
    r = client.post("/webhook", json=_payload("off-001", "gaste 500 en comida"))

    assert r.status_code == 200
    assert len(fake_wpp.sent_messages) == 1, fake_wpp.sent_messages
    sent = fake_wpp.sent_messages[0]
    assert sent["type"] == "text"
    assert sent["to"] == STORED_PHONE
    assert "ya no está disponible" in sent["text"]["body"]
    assert "https://app.jirens.test" in sent["text"]["body"]
    assert _session_estado() == WHATSAPP_OFF_NOTICE_STATE


def test_second_message_gets_no_reply(client, fake_wpp):
    client.post("/webhook", json=_payload("off-001"))
    fake_wpp.reset()

    r = client.post("/webhook", json=_payload("off-002", "hola de nuevo"))

    assert r.status_code == 200
    assert fake_wpp.sent_messages == []


def test_duplicate_message_id_gets_no_second_notice(client, fake_wpp):
    for _ in range(3):
        assert client.post("/webhook", json=_payload("off-dup")).status_code == 200

    assert len(fake_wpp.sent_messages) == 1
    with SessionLocal() as db:
        rows = db.execute(text("SELECT count(*) FROM processed_wpp_messages WHERE message_id = 'off-dup'"))
        assert rows.scalar_one() == 1


def test_an_existing_session_keeps_its_data_and_gets_the_notice_once(client, fake_wpp):
    """Someone mid-flow when the switch flipped still gets one notice, not the chatbot."""
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO chat_sessions (telephone, estado, expense_data, updated_at) "
                "VALUES (:t, 'esperando_monto', '{\"_sess_group_id\": 7}', now())"
            ),
            {"t": STORED_PHONE},
        )
        db.commit()

    client.post("/webhook", json=_payload("off-010"))
    client.post("/webhook", json=_payload("off-011"))

    assert len(fake_wpp.sent_messages) == 1
    assert _session_estado() == WHATSAPP_OFF_NOTICE_STATE


def test_status_callbacks_are_ignored(client, fake_wpp):
    r = client.post("/webhook", json={"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]})
    assert r.status_code == 200
    assert fake_wpp.sent_messages == []


def test_switching_back_on_resumes_the_chatbot(client, fake_wpp, monkeypatch):
    client.post("/webhook", json=_payload("off-020"))
    fake_wpp.reset()

    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    with patch("template.service_layer.whatsapp_service.time.sleep"):
        client.post("/webhook", json=_payload("off-021"))

    texts = fake_wpp.texts_sent()
    assert any("registr" in t.lower() for t in texts), f"expected the chatbot's reply, got: {texts}"
    assert _session_estado() != WHATSAPP_OFF_NOTICE_STATE


# ── Members, preferences and invitations through the API ─────────────────────


def test_choosing_whatsapp_is_rejected_and_email_is_the_default(client, auth_headers):
    """MemberUpdate is a plain BaseModel: the front (and this test) send snake_case."""
    me = client.get("/api/v1/members/me", headers=auth_headers).json()["data"]
    assert me["notificationPreference"] == NotificationType.EMAIL.value

    r = client.patch("/api/v1/members/me", json={"notification_preference": "WHATSAPP"}, headers=auth_headers)
    assert r.status_code == 400
    assert "WhatsApp" in r.json()["detail"]

    r = client.patch("/api/v1/members/me", json={"notification_preference": "NONE"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["notificationPreference"] == "NONE"


def test_a_stored_whatsapp_preference_is_left_alone(client, auth_headers, primary_member_id):
    with SessionLocal() as db:
        db.execute(
            text("UPDATE members SET notification_preference = 'WHATSAPP' WHERE id = :id"), {"id": primary_member_id}
        )
        db.commit()

    r = client.patch("/api/v1/members/me", json={"name": "Renamed"}, headers=auth_headers)

    assert r.status_code == 200
    assert r.json()["data"]["notificationPreference"] == "WHATSAPP"


def test_phone_invitation_sends_no_whatsapp_but_is_created(client, auth_headers, primary_group_id):
    with patch("template.service_layer.whatsapp_invite_client.enviar_mensaje_whatsapp") as send:
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Nico", "channel": "phone", "contact": "541199999999"},
            headers=auth_headers,
        )

    assert r.status_code in (200, 201), r.text
    send.assert_not_called()
    assert r.json()["data"]["shareUrl"]
    listed = client.get(f"/api/v1/groups/{primary_group_id}/invitations", headers=auth_headers).json()["data"]
    assert [i["target"] for i in listed] == ["541199999999"]
    with SessionLocal() as db:
        pref = db.execute(text("SELECT notification_preference FROM members WHERE name = 'Nico'")).scalar_one()
    assert pref == "EMAIL"
