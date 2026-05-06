"""Tests for the WhatsApp message-builder helpers."""

import json

from template.service_layer.whatsapp_service import (
    button_reply_message,
    list_reply_message,
    member_select_message,
)


def _decode(data: str) -> dict:
    return json.loads(data)


class TestMemberSelectMessage:
    def test_three_or_fewer_options_uses_button_reply(self):
        data = _decode(member_select_message("549123", ["Alice", "Bob", "Carol"], "pick", "footer", "ref"))
        assert data["interactive"]["type"] == "button"
        assert len(data["interactive"]["action"]["buttons"]) == 3

    def test_more_than_three_options_uses_list_reply(self):
        data = _decode(
            member_select_message(
                "549123",
                ["Alice", "Bob", "Carol", "Dan"],
                "pick",
                "footer",
                "ref",
            )
        )
        assert data["interactive"]["type"] == "list"
        rows = data["interactive"]["action"]["sections"][0]["rows"]
        assert [r["title"] for r in rows] == ["Alice", "Bob", "Carol", "Dan"]

    def test_single_option_still_uses_button_reply(self):
        data = _decode(member_select_message("549123", ["Solo"], "pick", "footer", "ref"))
        assert data["interactive"]["type"] == "button"

    def test_button_reply_directly_still_works(self):
        data = _decode(button_reply_message("549123", ["Yes", "No"], "ok?", "footer", "ref"))
        assert data["interactive"]["type"] == "button"

    def test_list_reply_directly_still_works(self):
        data = _decode(list_reply_message("549123", ["a", "b"], "pick", "footer", "ref"))
        assert data["interactive"]["type"] == "list"
