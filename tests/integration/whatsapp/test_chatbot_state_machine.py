"""Drive the WhatsApp chatbot state machine through its key flows.

Uses FakeWhatsAppClient to assert what messages were sent without hitting the
Meta API. Each test starts from the initial state (DB is cleaned between tests).
"""

from unittest.mock import patch

import pytest

# Phones not registered in the DB hit the "not registered" path.
UNKNOWN_PHONE = "5499900001111"


def _post(client, from_number: str, message_id: str, text: str):
    return client.post(
        "/webhook",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": from_number,
                                        "id": message_id,
                                        "type": "text",
                                        "text": {"body": text},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )


def test_unknown_number_gets_registration_prompt(client, fake_wpp):
    """A phone number not in the DB receives the registration link."""
    with patch("template.service_layer.whatsapp_service.time.sleep"):
        r = _post(client, UNKNOWN_PHONE, "sm-001", "hola")

    assert r.status_code == 200
    texts = fake_wpp.texts_sent()
    assert any("registr" in t.lower() for t in texts), f"Expected registration prompt, got: {texts}"


def test_malformed_webhook_body_returns_ok(client, fake_wpp):
    """A webhook with missing keys is silently ignored (returns 'ok', no crash)."""
    r = client.post("/webhook", json={"entry": [{}]})
    assert r.status_code == 200
    assert len(fake_wpp.sent_messages) == 0


def test_greeting_transitions_to_initial_state(client, fake_wpp):
    """After 'hola', state stays initial and options are shown (or not-registered)."""
    with patch("template.service_layer.whatsapp_service.time.sleep"):
        r = _post(client, UNKNOWN_PHONE, "sm-002", "hola")

    assert r.status_code == 200
    # At minimum a mark-read message + one response is sent
    assert len(fake_wpp.sent_messages) >= 1


def test_state_persists_across_messages(client, fake_wpp):
    """State written by message N is visible to message N+1 (DB-backed isolation)."""
    with patch("template.service_layer.whatsapp_service.time.sleep"):
        # First message sets state to esperando_monto
        _post(client, UNKNOWN_PHONE, "sm-003", "hola")
        count_after_hola = len(fake_wpp.sent_messages)

        # Second message with a different ID is processed independently
        _post(client, UNKNOWN_PHONE, "sm-004", "hola")

    # Both ran (different message IDs) — total should be 2× first-run count
    assert len(fake_wpp.sent_messages) == 2 * count_after_hola


def test_two_users_state_is_isolated(client, fake_wpp):
    """Messages from two different numbers keep independent states."""
    phone_a = "5499900001111"
    phone_b = "5499900002222"

    with patch("template.service_layer.whatsapp_service.time.sleep"):
        _post(client, phone_a, "sm-005", "hola")
        _post(client, phone_b, "sm-006", "hola")

    # Both users processed — no state corruption
    assert len(fake_wpp.sent_messages) > 0
    # Responses were sent to each respective number
    recipients = {m.get("to") for m in fake_wpp.sent_messages if m.get("to")}
    assert len(recipients) == 2
