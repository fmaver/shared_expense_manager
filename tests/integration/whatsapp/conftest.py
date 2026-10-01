"""The chatbot tests here exercise WhatsApp as it works when switched on.

WHATSAPP_ENABLED is off by default, which stops the chatbot at the webhook. These tests keep
the old behaviour covered so the switch stays reversible; `test_whatsapp_off.py` overrides
this fixture to test the switched-off webhook.
"""

import pytest


@pytest.fixture(name="_whatsapp_switch", autouse=True)
def _switch_on(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
