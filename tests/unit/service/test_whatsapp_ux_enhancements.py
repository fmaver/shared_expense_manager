"""Tests for WhatsApp chatbot UX enhancements: date parsing, amount normalization,
payment type, cancel keyword, category picker, display helpers."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.service_layer.whatsapp_service import (
    administrar_chatbot,
    format_category_es,
    format_date_es,
    format_member_name_es,
    format_payment_type_es,
    handle_waiting_for_amount,
    handle_waiting_for_amount_for_member,
    handle_waiting_for_category,
    handle_waiting_for_confirmation,
    handle_waiting_for_excluded_members,
    handle_waiting_for_installments,
    handle_waiting_for_participants_definition,
    handle_waiting_for_payment_date,
    handle_waiting_for_payment_type,
    handle_waiting_for_split_strategy,
    parse_user_date,
)


def _decode(data: str) -> dict:
    return json.loads(data)


def _make_member(mid: int, name: str):
    m = MagicMock()
    m.id = mid
    m.name = name
    return m


def _base_expense_estado(service: str = "cargar gasto", payer_id: int = 1):
    return {
        "estado": "esperando_descripcion",
        "expense_data": {
            "service": service,
            "payer_id": payer_id,
            "description": "test",
            "amount": 100.0,
            "installments": 1,
        },
    }


# ---------------------------------------------------------------------------
# parse_user_date
# ---------------------------------------------------------------------------


class TestParseUserDate:
    def test_hoy_returns_today(self):
        result = parse_user_date("hoy")
        assert result == date.today()

    def test_ayer_returns_yesterday(self):
        from datetime import timedelta

        result = parse_user_date("ayer")
        assert result == date.today() - timedelta(days=1)

    def test_dd_mm_yyyy_dash(self):
        result = parse_user_date("15-03-2025")
        assert result == date(2025, 3, 15)

    def test_dd_mm_yyyy_slash(self):
        result = parse_user_date("15/03/2025")
        assert result == date(2025, 3, 15)

    def test_dd_mm_current_year_dash(self):
        result = parse_user_date("15-03")
        assert result == date(date.today().year, 3, 15)

    def test_dd_mm_current_year_slash(self):
        result = parse_user_date("15/03")
        assert result == date(date.today().year, 3, 15)

    def test_case_insensitive_keywords(self):
        assert parse_user_date("HOY") == date.today()
        assert parse_user_date("Hoy") == date.today()

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            parse_user_date("garbage")

    def test_invalid_date_wrong_format_raises(self):
        with pytest.raises(ValueError):
            parse_user_date("2025-03-15")  # ISO format not accepted


# ---------------------------------------------------------------------------
# format_date_es
# ---------------------------------------------------------------------------


class TestFormatDateEs:
    def test_iso_to_display(self):
        assert format_date_es("2025-03-15") == "15/03/2025"

    def test_invalid_passthrough(self):
        assert format_date_es("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# format_payment_type_es
# ---------------------------------------------------------------------------


class TestFormatPaymentTypeEs:
    def test_debito(self):
        assert format_payment_type_es("debito", 1) == "Débito"

    def test_credito_1_cuota(self):
        assert format_payment_type_es("credito", 1) == "Crédito (1 cuota)"

    def test_credito_with_accent_1_cuota(self):
        assert format_payment_type_es("crédito", 1) == "Crédito (1 cuota)"

    def test_credito_multi_cuotas(self):
        assert format_payment_type_es("credito", 12) == "Crédito (12 cuotas)"

    def test_credito_many_cuotas(self):
        assert format_payment_type_es("credito", 36) == "Crédito (36 cuotas)"


# ---------------------------------------------------------------------------
# format_category_es
# ---------------------------------------------------------------------------


class TestFormatCategoryEs:
    def test_known_category_with_emoji(self):
        result = format_category_es("salud")
        assert "Salud" in result
        assert "💊" in result

    def test_prestamo_special_case(self):
        result = format_category_es("prestamo")
        assert "Préstamo" in result

    def test_viajes(self):
        result = format_category_es("viajes")
        assert "Viajes" in result
        assert "✈️" in result


# ---------------------------------------------------------------------------
# format_member_name_es
# ---------------------------------------------------------------------------


class TestFormatMemberNameEs:
    def test_known_member(self):
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"
        assert format_member_name_es(1, ms) == "Alice"

    def test_unknown_member_fallback(self):
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = None
        assert format_member_name_es(99, ms) == "Desconocido"


# ---------------------------------------------------------------------------
# Amount: comma normalization
# ---------------------------------------------------------------------------


class TestHandleWaitingForAmountComma:
    def test_comma_decimal_accepted(self):
        estado = {"estado": "esperando_monto", "expense_data": {"service": "cargar gasto"}}
        responses, new_estado = handle_waiting_for_amount("549123", estado, "msg1", "1234,56")
        assert new_estado["expense_data"]["amount"] == 1234.56
        assert new_estado["estado"] == "esperando_descripcion"

    def test_dot_decimal_still_accepted(self):
        estado = {"estado": "esperando_monto", "expense_data": {"service": "cargar gasto"}}
        responses, new_estado = handle_waiting_for_amount("549123", estado, "msg1", "99.50")
        assert new_estado["expense_data"]["amount"] == 99.50

    def test_invalid_amount_returns_error(self):
        estado = {"estado": "esperando_monto", "expense_data": {"service": "cargar gasto"}}
        responses, new_estado = handle_waiting_for_amount("549123", estado, "msg1", "abc")
        assert new_estado["estado"] == "esperando_monto"
        assert len(responses) == 1


# ---------------------------------------------------------------------------
# Date entry: new formats + hoy/ayer in handle_waiting_for_payment_date
# ---------------------------------------------------------------------------


class TestHandleWaitingForPaymentDateNewFormats:
    def _member_service(self):
        ms = MagicMock()
        ms.list_members.return_value = [_make_member(1, "Alice"), _make_member(2, "Bob")]
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob"}[mid]
        ms.get_member_names.return_value = {1: "Alice", 2: "Bob"}
        return ms

    def _estado(self):
        return {
            "estado": "esperando_fecha_pago",
            "expense_data": {"service": "cargar gasto", "payer_id": 1, "amount": 100.0, "installments": 1},
        }

    def test_hoy_accepted(self):
        ms = self._member_service()
        _, new_estado = handle_waiting_for_payment_date("549123", self._estado(), "hoy", ms, "msg1")
        assert new_estado["estado"] == "esperando_categoria"
        assert new_estado["expense_data"]["date"] == date.today().isoformat()

    def test_dd_mm_slash_current_year_accepted(self):
        ms = self._member_service()
        _, new_estado = handle_waiting_for_payment_date("549123", self._estado(), "15/03", ms, "msg1")
        assert new_estado["estado"] == "esperando_categoria"
        expected = date(date.today().year, 3, 15).isoformat()
        assert new_estado["expense_data"]["date"] == expected

    def test_slash_format_accepted(self):
        ms = self._member_service()
        _, new_estado = handle_waiting_for_payment_date("549123", self._estado(), "15/03/2025", ms, "msg1")
        assert new_estado["estado"] == "esperando_categoria"
        assert new_estado["expense_data"]["date"] == "2025-03-15"

    def test_dd_mm_current_year_accepted(self):
        ms = self._member_service()
        _, new_estado = handle_waiting_for_payment_date("549123", self._estado(), "15-03", ms, "msg1")
        assert new_estado["estado"] == "esperando_categoria"
        expected = date(date.today().year, 3, 15).isoformat()
        assert new_estado["expense_data"]["date"] == expected

    def test_invalid_date_returns_error(self):
        ms = self._member_service()
        responses, new_estado = handle_waiting_for_payment_date("549123", self._estado(), "garbage", ms, "msg1")
        assert new_estado["estado"] == "esperando_fecha_pago"
        assert len(responses) == 1

    def test_category_prompt_is_interactive_list(self):
        ms = self._member_service()
        responses, _ = handle_waiting_for_payment_date("549123", self._estado(), "hoy", ms, "msg1")
        data = _decode(responses[0])
        assert data["type"] == "interactive"
        assert data["interactive"]["type"] == "list"


# ---------------------------------------------------------------------------
# Payment type: 3 buttons
# ---------------------------------------------------------------------------


class TestHandleWaitingForPaymentType:
    def _estado(self):
        return {
            "estado": "esperando_tipo_pago",
            "expense_data": {"service": "cargar gasto", "installments": 1},
        }

    def test_debito_goes_to_estrategia(self):
        _, new = handle_waiting_for_payment_type("549123", self._estado(), "msg1", "💰 Débito")
        assert new["expense_data"]["payment_type"] == "debito"
        assert new["estado"] == "esperando_estrategia"

    def test_credito_1_cuota_skips_cuotas(self):
        _, new = handle_waiting_for_payment_type("549123", self._estado(), "msg1", "💳 Crédito 1 cuota")
        assert new["expense_data"]["payment_type"] == "credito"
        assert new["expense_data"]["installments"] == 1
        assert new["estado"] == "esperando_estrategia"

    def test_credito_en_cuotas_goes_to_cuotas(self):
        _, new = handle_waiting_for_payment_type("549123", self._estado(), "msg1", "💳 Crédito en cuotas")
        assert new["expense_data"]["payment_type"] == "credito"
        assert new["estado"] == "esperando_cuotas"


# ---------------------------------------------------------------------------
# Installments: require >= 2
# ---------------------------------------------------------------------------


class TestHandleWaitingForInstallments:
    def _estado(self):
        return {"estado": "esperando_cuotas", "expense_data": {"payment_type": "credito"}}

    def test_valid_installments_accepted(self):
        _, new = handle_waiting_for_installments("549123", self._estado(), "12")
        assert new["expense_data"]["installments"] == 12
        assert new["estado"] == "esperando_estrategia"

    def test_large_installments_accepted(self):
        _, new = handle_waiting_for_installments("549123", self._estado(), "48")
        assert new["expense_data"]["installments"] == 48

    def test_one_rejected(self):
        responses, new = handle_waiting_for_installments("549123", self._estado(), "1")
        assert new["estado"] == "esperando_cuotas"
        assert len(responses) == 1

    def test_zero_rejected(self):
        responses, new = handle_waiting_for_installments("549123", self._estado(), "0")
        assert new["estado"] == "esperando_cuotas"

    def test_non_integer_rejected(self):
        responses, new = handle_waiting_for_installments("549123", self._estado(), "abc")
        assert new["estado"] == "esperando_cuotas"


# ---------------------------------------------------------------------------
# Category picker: interactive list ID matching
# ---------------------------------------------------------------------------


class TestHandleWaitingForCategory:
    def _estado(self):
        return {
            "estado": "esperando_categoria",
            "expense_data": {"service": "cargar gasto"},
        }

    def test_cat_id_resolves_category(self):
        _, new = handle_waiting_for_category("549123", self._estado(), "Salud 💊", "msg1", "cat_salud")
        assert new["expense_data"]["category"] == "salud"
        assert new["estado"] == "esperando_tipo_pago"

    def test_cat_id_viajes_resolves(self):
        _, new = handle_waiting_for_category("549123", self._estado(), "Viajes ✈️", "msg1", "cat_viajes")
        assert new["expense_data"]["category"] == "viajes"
        assert new["estado"] == "esperando_tipo_pago"

    def test_no_interactive_id_shows_error_and_list(self):
        # Without an interactive_id the user typed something — re-show the list
        responses, new = handle_waiting_for_category("549123", self._estado(), "1", "msg1", None)
        assert new["estado"] == "esperando_categoria"
        assert len(responses) == 2

    def test_typed_name_without_id_shows_error(self):
        responses, new = handle_waiting_for_category("549123", self._estado(), "viajes", "msg1", None)
        assert new["estado"] == "esperando_categoria"
        assert len(responses) == 2

    def test_internal_category_rejected(self):
        responses, new = handle_waiting_for_category("549123", self._estado(), "balance", "msg1", "cat_balance")
        assert new["estado"] == "esperando_categoria"

    def test_payment_type_prompt_has_3_buttons(self):
        responses, _ = handle_waiting_for_category("549123", self._estado(), "Salud 💊", "msg1", "cat_salud")
        data = _decode(responses[0])
        assert data["interactive"]["type"] == "button"
        buttons = data["interactive"]["action"]["buttons"]
        assert len(buttons) == 3


# ---------------------------------------------------------------------------
# Confirmation success resets state
# ---------------------------------------------------------------------------


class TestHandleWaitingForConfirmationReset:
    def _estado(self):
        return {
            "estado": "esperando_confirmacion",
            "expense_data": {
                "service": "cargar gasto",
                "description": "test",
                "amount": 100.0,
                "date": "2025-03-15",
                "category": "salud",
                "payer_id": 1,
                "payment_type": "debito",
                "installments": 1,
                "split_strategy": {"type": "equal", "percentages": None},
            },
        }

    def test_confirm_resets_state_to_inicial(self):
        service = MagicMock()
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        with patch("template.service_layer.whatsapp_service.create_expense"):
            _, new = handle_waiting_for_confirmation("549123", self._estado(), "✅ Sí, crear gasto", service, ms)

        assert new["estado"] == "inicial"
        assert new["expense_data"]["amount"] is None

    def test_cancel_resets_state(self):
        service = MagicMock()
        ms = MagicMock()
        _, new = handle_waiting_for_confirmation("549123", self._estado(), "❌ No, cancelar", service, ms)
        assert new["estado"] == "inicial"


# ---------------------------------------------------------------------------
# Global cancel keyword in administrar_chatbot
# ---------------------------------------------------------------------------


class TestGlobalCancelKeyword:
    def _estado_mid_flow(self):
        return {
            "estado": "esperando_monto",
            "expense_data": {
                "service": "cargar gasto",
                "description": None,
                "amount": None,
                "date": None,
                "category": None,
                "payer_id": None,
                "payment_type": None,
                "installments": 1,
                "split_strategy": None,
            },
        }

    def test_cancelar_from_mid_flow_resets_to_inicial(self):
        ms = MagicMock()
        ms.get_member_name_by_phone.return_value = "Alice"
        ms.get_member_name_by_id.return_value = "Alice"
        wpp = MagicMock()

        estado = self._estado_mid_flow()
        new = administrar_chatbot("cancelar", "549123", "msg1", estado, MagicMock(), ms, wpp)
        assert new["estado"] == "inicial"

    def test_cancelar_sends_cancellation_notice(self):
        ms = MagicMock()
        ms.get_member_name_by_phone.return_value = "Alice"
        ms.get_member_name_by_id.return_value = "Alice"
        sent_messages = []
        wpp = MagicMock()
        wpp.send_message.side_effect = lambda m: sent_messages.append(m)

        estado = self._estado_mid_flow()
        administrar_chatbot("cancelar", "549123", "msg1", estado, MagicMock(), ms, wpp)

        texts = [_decode(m).get("text", {}).get("body", "") for m in sent_messages if '"type": "text"' in m]
        assert any("cancelada" in t.lower() for t in texts)


# ---------------------------------------------------------------------------
# Split strategy: 3-button prompt
# ---------------------------------------------------------------------------


class TestHandleWaitingForSplitStrategy:
    def _ms_4(self):
        ms = MagicMock()
        members = [_make_member(i, n) for i, n in [(1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Dave")]]
        ms.list_members.return_value = members
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol", 4: "Dave"}[mid]
        return ms

    def _ms_2(self):
        ms = MagicMock()
        members = [_make_member(1, "Alice"), _make_member(2, "Bob")]
        ms.list_members.return_value = members
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob"}[mid]
        return ms

    def _estado(self, payer_id=1):
        return {
            "estado": "esperando_estrategia",
            "expense_data": {
                "service": "cargar gasto",
                "payer_id": payer_id,
                "amount": 1000.0,
                "description": "test",
                "date": "2025-03-15",
                "category": "salud",
                "payment_type": "debito",
                "installments": 1,
                "split_strategy": None,
            },
        }

    def test_partes_iguales_2_members_goes_to_confirmation(self):
        ms = self._ms_2()
        _, new = handle_waiting_for_split_strategy("549123", self._estado(), "msg1", "⚖️ Partes iguales", ms)
        assert new["estado"] == "esperando_confirmacion"
        assert new["expense_data"]["split_strategy"]["type"] == "equal"

    def test_partes_iguales_4_members_goes_to_definicion_participantes(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_split_strategy("549123", self._estado(), "msg1", "⚖️ Partes iguales", ms)
        assert new["estado"] == "esperando_definicion_participantes"

    def test_partes_iguales_via_interactive_id(self):
        ms = self._ms_2()
        _, new = handle_waiting_for_split_strategy(
            "549123", self._estado(), "msg1", "", ms, interactive_id="sed_split_btn_1"
        )
        assert new["estado"] == "esperando_confirmacion"

    def test_porcentajes_via_button_id(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_split_strategy(
            "549123", self._estado(), "msg1", "", ms, interactive_id="sed_split_btn_2"
        )
        assert new["estado"] == "esperando_porcentaje_para_miembro"

    def test_montos_exactos_via_button_id_enters_queue(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_split_strategy(
            "549123", self._estado(), "msg1", "", ms, interactive_id="sed_split_btn_3"
        )
        assert new["estado"] == "esperando_monto_para_miembro"
        assert new["expense_data"]["pending_amounts"] == {}
        assert len(new["expense_data"]["remaining_member_ids"]) == 3  # non-payer IDs

    def test_montos_exactos_via_text(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_split_strategy("549123", self._estado(), "msg1", "💵 Montos exactos", ms)
        assert new["estado"] == "esperando_monto_para_miembro"


# ---------------------------------------------------------------------------
# Participants definition: Todos vs Excluir
# ---------------------------------------------------------------------------


class TestHandleWaitingForParticipantsDefinition:
    def _ms_4(self):
        ms = MagicMock()
        members = [_make_member(i, n) for i, n in [(1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Dave")]]
        ms.list_members.return_value = members
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol", 4: "Dave"}[mid]
        return ms

    def _estado(self):
        return {
            "estado": "esperando_definicion_participantes",
            "expense_data": {
                "service": "cargar gasto",
                "payer_id": 1,
                "amount": 300.0,
                "description": "test",
                "date": "2025-03-15",
                "category": "salud",
                "payment_type": "debito",
                "installments": 1,
                "split_strategy": None,
            },
        }

    def test_todos_goes_to_confirmation_with_equal_all(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_participants_definition("549123", self._estado(), "👥 Todos participan", ms)
        assert new["estado"] == "esperando_confirmacion"
        assert new["expense_data"]["split_strategy"] == {"type": "equal"}

    def test_todos_via_button_id(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_participants_definition(
            "549123", self._estado(), "", ms, interactive_id="sed_part_btn_1"
        )
        assert new["estado"] == "esperando_confirmacion"

    def test_excluir_via_button_id_enters_excluidos(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_participants_definition(
            "549123", self._estado(), "", ms, interactive_id="sed_part_btn_2"
        )
        assert new["estado"] == "esperando_excluidos"
        assert new["expense_data"]["excluded_member_ids"] == []

    def test_excluir_via_text_enters_excluidos(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_participants_definition("549123", self._estado(), "✂️ Excluir a alguien", ms)
        assert new["estado"] == "esperando_excluidos"


# ---------------------------------------------------------------------------
# Excluded members toggle list
# ---------------------------------------------------------------------------


class TestHandleWaitingForExcludedMembers:
    def _ms_4(self):
        ms = MagicMock()
        members = [_make_member(i, n) for i, n in [(1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Dave")]]
        ms.list_members.return_value = members
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol", 4: "Dave"}[mid]
        return ms

    def _estado(self, excluded=None):
        return {
            "estado": "esperando_excluidos",
            "expense_data": {
                "service": "cargar gasto",
                "payer_id": 1,
                "amount": 300.0,
                "description": "test",
                "date": "2025-03-15",
                "category": "salud",
                "payment_type": "debito",
                "installments": 1,
                "split_strategy": None,
                "excluded_member_ids": excluded or [],
                "all_member_ids": [1, 2, 3, 4],
            },
        }

    def test_tap_member_adds_to_excluded_and_re_prompts(self):
        ms = self._ms_4()
        responses, new = handle_waiting_for_excluded_members("549123", self._estado(), ms, interactive_id="exc_2")
        assert 2 in new["expense_data"]["excluded_member_ids"]
        assert new["estado"] == "esperando_excluidos"
        data = _decode(responses[0])
        assert data["type"] == "interactive"

    def test_listo_with_one_excluded_stores_participant_ids(self):
        ms = self._ms_4()
        estado = self._estado(excluded=[2])
        _, new = handle_waiting_for_excluded_members("549123", estado, ms, interactive_id="exc_done")
        assert new["estado"] == "esperando_confirmacion"
        strategy = new["expense_data"]["split_strategy"]
        assert strategy["type"] == "equal"
        assert 2 not in strategy["participant_ids"]
        assert set(strategy["participant_ids"]) == {1, 3, 4}

    def test_listo_with_no_exclusions_stores_equal_all(self):
        ms = self._ms_4()
        _, new = handle_waiting_for_excluded_members("549123", self._estado(), ms, interactive_id="exc_done")
        assert new["estado"] == "esperando_confirmacion"
        assert new["expense_data"]["split_strategy"] == {"type": "equal"}

    def test_excluding_everyone_re_prompts_with_error(self):
        ms = self._ms_4()
        estado = self._estado(excluded=[1, 2, 3, 4])
        responses, new = handle_waiting_for_excluded_members("549123", estado, ms, interactive_id="exc_done")
        assert new["estado"] == "esperando_excluidos"
        assert len(responses) == 2

    def test_queue_keys_cleaned_up_after_listo(self):
        ms = self._ms_4()
        estado = self._estado(excluded=[2])
        _, new = handle_waiting_for_excluded_members("549123", estado, ms, interactive_id="exc_done")
        assert "excluded_member_ids" not in new["expense_data"]
        assert "all_member_ids" not in new["expense_data"]


# ---------------------------------------------------------------------------
# Exact amounts per member
# ---------------------------------------------------------------------------


class TestHandleWaitingForAmountForMember:
    def _ms(self):
        ms = MagicMock()
        members = [_make_member(i, n) for i, n in [(1, "Alice"), (2, "Bob"), (3, "Carol")]]
        ms.list_members.return_value = members
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol"}[mid]
        return ms

    def _estado(self, remaining=None, pending=None):
        return {
            "estado": "esperando_monto_para_miembro",
            "expense_data": {
                "service": "cargar gasto",
                "payer_id": 1,
                "amount": 1000.0,
                "description": "test",
                "date": "2025-03-15",
                "category": "salud",
                "payment_type": "debito",
                "installments": 1,
                "split_strategy": None,
                "remaining_member_ids": remaining if remaining is not None else [2, 3],
                "pending_amounts": pending or {},
            },
        }

    def test_first_amount_stores_and_advances_queue(self):
        ms = self._ms()
        _, new = handle_waiting_for_amount_for_member("549123", self._estado(), "300", "msg1", ms)
        assert new["expense_data"]["pending_amounts"][2] == 300.0
        assert new["expense_data"]["remaining_member_ids"] == [3]
        assert new["estado"] == "esperando_monto_para_miembro"

    def test_comma_decimal_accepted(self):
        ms = self._ms()
        _, new = handle_waiting_for_amount_for_member("549123", self._estado(), "250,50", "msg1", ms)
        assert new["expense_data"]["pending_amounts"][2] == 250.5

    def test_last_amount_finalises_with_payer_remainder(self):
        ms = self._ms()
        estado = self._estado(remaining=[3], pending={2: 300.0})
        _, new = handle_waiting_for_amount_for_member("549123", estado, "250", "msg1", ms)
        assert new["estado"] == "esperando_confirmacion"
        strategy = new["expense_data"]["split_strategy"]
        assert strategy["type"] == "exact"
        assert strategy["amounts"][1] == 450.0  # payer remainder
        assert strategy["amounts"][2] == 300.0
        assert strategy["amounts"][3] == 250.0

    def test_overflow_rejected(self):
        ms = self._ms()
        estado = self._estado(remaining=[3], pending={2: 900.0})
        responses, new = handle_waiting_for_amount_for_member("549123", estado, "200", "msg1", ms)
        assert new["estado"] == "esperando_monto_para_miembro"
        assert len(responses) == 1

    def test_negative_amount_rejected(self):
        ms = self._ms()
        responses, new = handle_waiting_for_amount_for_member("549123", self._estado(), "-50", "msg1", ms)
        assert new["estado"] == "esperando_monto_para_miembro"
        assert len(responses) == 1

    def test_zero_amount_allowed(self):
        ms = self._ms()
        _, new = handle_waiting_for_amount_for_member("549123", self._estado(), "0", "msg1", ms)
        assert new["expense_data"]["pending_amounts"][2] == 0.0

    def test_queue_keys_cleaned_after_finalise(self):
        ms = self._ms()
        estado = self._estado(remaining=[3], pending={2: 300.0})
        _, new = handle_waiting_for_amount_for_member("549123", estado, "250", "msg1", ms)
        assert "pending_amounts" not in new["expense_data"]
        assert "remaining_member_ids" not in new["expense_data"]


# ---------------------------------------------------------------------------
# Summary rendering for new strategies
# ---------------------------------------------------------------------------


class TestGetExpenseSummaryNewStrategies:
    def _ms(self):
        ms = MagicMock()
        ms.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol"}[mid]
        return ms

    def _expense_data(self, strategy):
        return {
            "service": "cargar gasto",
            "description": "carne",
            "amount": 900.0,
            "date": "2025-03-15",
            "category": "salud",
            "payer_id": 1,
            "payment_type": "debito",
            "installments": 1,
            "split_strategy": strategy,
        }

    def test_subset_equal_shows_participant_names(self):
        from template.service_layer.whatsapp_service import get_expense_summary

        ms = self._ms()
        data = self._expense_data({"type": "equal", "participant_ids": [1, 3]})
        summary = get_expense_summary(data, ms)
        assert "Alice" in summary
        assert "Carol" in summary
        assert "Partes iguales entre" in summary

    def test_exact_amounts_shows_per_member_dollars(self):
        from template.service_layer.whatsapp_service import get_expense_summary

        ms = self._ms()
        data = self._expense_data({"type": "exact", "amounts": {1: 300.0, 2: 300.0, 3: 300.0}})
        summary = get_expense_summary(data, ms)
        assert "Montos asignados" in summary
        assert "$300,00" in summary

    def test_equal_all_shows_partes_iguales(self):
        from template.service_layer.whatsapp_service import get_expense_summary

        ms = self._ms()
        data = self._expense_data({"type": "equal"})
        summary = get_expense_summary(data, ms)
        assert "Partes iguales" in summary
        assert "entre" not in summary
