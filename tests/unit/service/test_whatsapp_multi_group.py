"""Tests for multi-group WhatsApp bot behaviour."""

import json
from unittest.mock import MagicMock

from template.service_layer.whatsapp_service import (
    handle_cambiar_grupo,
    handle_greetings,
)


def _make_group(gid: int, name: str):
    g = MagicMock()
    g.id = gid
    g.name = name
    return g


def _make_member_service(name: str = "Fran"):
    svc = MagicMock()
    svc.get_member_name_by_phone.return_value = name
    return svc


def _decode(msg: str) -> dict:
    return json.loads(msg)


def _initial_estado(group_id=None):
    estado = {"estado": "inicial", "expense_data": {}}
    if group_id is not None:
        estado["group_id"] = group_id
    return estado


# ---------------------------------------------------------------------------
# handle_greetings — single group
# ---------------------------------------------------------------------------


class TestGreetingsSingleGroup:
    def test_uses_button_reply_for_single_group(self):
        groups = [_make_group(1, "Casa")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        msg = _decode(responses[0])
        assert msg["interactive"]["type"] == "button"

    def test_shows_three_options_for_single_group(self):
        groups = [_make_group(1, "Casa")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        buttons = _decode(responses[0])["interactive"]["action"]["buttons"]
        assert len(buttons) == 3

    def test_greeting_includes_active_group_name(self):
        groups = [_make_group(1, "Casa")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        body = _decode(responses[0])["interactive"]["body"]["text"]
        assert "Casa" in body

    def test_no_cambiar_grupo_option_for_single_group(self):
        groups = [_make_group(1, "Casa")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        buttons = _decode(responses[0])["interactive"]["action"]["buttons"]
        titles = [b["reply"]["title"] for b in buttons]
        assert not any("Cambiar" in t for t in titles)


# ---------------------------------------------------------------------------
# handle_greetings — multiple groups
# ---------------------------------------------------------------------------


class TestGreetingsMultipleGroups:
    def test_uses_list_reply_for_multiple_groups(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        msg = _decode(responses[0])
        assert msg["interactive"]["type"] == "list"

    def test_shows_four_options_for_multiple_groups(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        rows = _decode(responses[0])["interactive"]["action"]["sections"][0]["rows"]
        assert len(rows) == 4

    def test_cambiar_grupo_is_fourth_option(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        rows = _decode(responses[0])["interactive"]["action"]["sections"][0]["rows"]
        titles = [r["title"] for r in rows]
        assert any("Cambiar" in t for t in titles)

    def test_active_group_name_shown_in_greeting(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_greetings("54111", _initial_estado(group_id=2), _make_member_service(), groups)
        body = _decode(responses[0])["interactive"]["body"]["text"]
        assert "Trabajo" in body

    def test_stores_known_group_ids_in_state(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        _, new_estado = handle_greetings("54111", _initial_estado(1), _make_member_service(), groups)
        assert set(new_estado["known_group_ids"]) == {1, 2}


# ---------------------------------------------------------------------------
# handle_greetings — new group detection
# ---------------------------------------------------------------------------


class TestNewGroupDetection:
    def test_notifies_when_user_joined_new_group(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Amigos")]
        # known_group_ids only has group 1 — group 2 is new
        estado = _initial_estado(1)
        estado["known_group_ids"] = [1]

        responses, _ = handle_greetings("54111", estado, _make_member_service(), groups)

        combined = " ".join(responses)
        assert "Amigos" in combined

    def test_no_notification_on_first_greeting(self):
        """First ever greeting — known_group_ids is empty, no "new group" noise."""
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        estado = _initial_estado(1)  # no known_group_ids key

        responses, _ = handle_greetings("54111", estado, _make_member_service(), groups)

        # Only one message (the menu) — no extra notification
        assert len(responses) == 1

    def test_no_notification_when_groups_unchanged(self):
        groups = [_make_group(1, "Casa")]
        estado = _initial_estado(1)
        estado["known_group_ids"] = [1]

        responses, _ = handle_greetings("54111", estado, _make_member_service(), groups)

        assert len(responses) == 1


# ---------------------------------------------------------------------------
# handle_cambiar_grupo
# ---------------------------------------------------------------------------


class TestHandleCambiarGrupo:
    def test_clears_group_id_from_state(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        estado = _initial_estado(group_id=1)

        _, new_estado = handle_cambiar_grupo("54111", estado, groups)

        assert "group_id" not in new_estado

    def test_sets_state_to_esperando_seleccion_grupo(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        _, new_estado = handle_cambiar_grupo("54111", _initial_estado(1), groups)
        assert new_estado["estado"] == "esperando_seleccion_grupo"

    def test_returns_list_interactive_message(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_cambiar_grupo("54111", _initial_estado(1), groups)
        msg = _decode(responses[0])
        assert msg["interactive"]["type"] == "list"

    def test_group_rows_use_grp_id_format(self):
        groups = [_make_group(7, "Casa"), _make_group(13, "Trabajo")]
        responses, _ = handle_cambiar_grupo("54111", _initial_estado(7), groups)
        rows = _decode(responses[0])["interactive"]["action"]["sections"][0]["rows"]
        ids = [r["id"] for r in rows]
        assert "grp_7" in ids
        assert "grp_13" in ids

    def test_group_names_shown_as_row_titles(self):
        groups = [_make_group(1, "Casa"), _make_group(2, "Trabajo")]
        responses, _ = handle_cambiar_grupo("54111", _initial_estado(1), groups)
        rows = _decode(responses[0])["interactive"]["action"]["sections"][0]["rows"]
        titles = [r["title"] for r in rows]
        assert "Casa" in titles
        assert "Trabajo" in titles
