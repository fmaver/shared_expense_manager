"""Verify that replaying the same WhatsApp message_id only triggers one response.

This covers the cold-boot retry-storm bug: when Render spins up slowly, Meta
retries the webhook several times. Each retry carries the same message_id and
must be silently discarded after the first one is processed.
"""

from unittest.mock import patch


def _make_payload(from_number: str, message_id: str, text: str) -> dict:
    return {
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
    }


def test_duplicate_message_id_processed_only_once(client, fake_wpp):
    """Five POSTs with the same message_id should produce only one chatbot run."""
    payload = _make_payload("5499900001111", "idem-test-001", "hola")

    with patch("template.service_layer.whatsapp_service.time.sleep"):
        # First request — should be processed
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    messages_after_first = len(fake_wpp.sent_messages)
    assert messages_after_first > 0, "expected chatbot to send at least one message"

    with patch("template.service_layer.whatsapp_service.time.sleep"):
        for _ in range(4):
            r = client.post("/webhook", json=payload)
            assert r.status_code == 200

    # No additional messages from the four duplicate deliveries
    assert len(fake_wpp.sent_messages) == messages_after_first


def test_different_message_ids_each_processed(client, fake_wpp):
    """Two messages with different IDs should both be processed."""
    with patch("template.service_layer.whatsapp_service.time.sleep"):
        r1 = client.post("/webhook", json=_make_payload("5499900001111", "msg-001", "hola"))
        r2 = client.post("/webhook", json=_make_payload("5499900001111", "msg-002", "hola"))

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both triggered a chatbot run → total messages > single-run count
    assert len(fake_wpp.sent_messages) >= 2
