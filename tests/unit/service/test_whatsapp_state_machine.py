"""Tests for WhatsApp state-machine handlers — N-member scenarios."""

import json
from unittest.mock import MagicMock

from template.service_layer.whatsapp_service import (
    handle_waiting_for_description,
    handle_waiting_for_loan_recipient,
    handle_waiting_for_payment_date,
    handle_waiting_for_percentage,
    handle_waiting_for_percentage_for_member,
    handle_waiting_for_split_strategy,
)


def _decode(data: str) -> dict:
    return json.loads(data)


def _make_member(mid: int, name: str):
    m = MagicMock()
    m.id = mid
    m.name = name
    return m


def _base_estado(service: str = "cargar gasto", payer_id: int = 1):
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


class TestHandleWaitingForDescriptionMemberSelect:
    def test_four_members_produces_list_reply(self):
        """When >3 members, the payer picker should use list_reply not button_reply."""
        expense_service = MagicMock()
        expense_service.get_member_names.return_value = {1: "Alice", 2: "Bob", 3: "Carol", 4: "Dan"}
        estado = {"estado": "esperando_descripcion", "expense_data": {"service": "cargar gasto"}}

        responses, _ = handle_waiting_for_description("549123", estado, "supermercado", expense_service)

        data = _decode(responses[0])
        assert data["interactive"]["type"] == "list"

    def test_three_members_produces_button_reply(self):
        """≤3 members should still use the compact button_reply."""
        expense_service = MagicMock()
        expense_service.get_member_names.return_value = {1: "Alice", 2: "Bob", 3: "Carol"}
        estado = {"estado": "esperando_descripcion", "expense_data": {"service": "cargar gasto"}}

        responses, _ = handle_waiting_for_description("549123", estado, "supermercado", expense_service)

        data = _decode(responses[0])
        assert data["interactive"]["type"] == "button"


class TestHandleWaitingForPaymentDateLoan:
    def test_two_members_auto_assigns_recipient_and_confirms(self):
        """2-member loan: non-payer is inferred; state → esperando_confirmacion."""
        member_service = MagicMock()
        member_service.list_members.return_value = [_make_member(1, "Alice"), _make_member(2, "Bob")]
        member_service.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob"}[mid]
        member_service.get_member_names.return_value = {1: "Alice", 2: "Bob"}

        estado = _base_estado(service="prestar plata", payer_id=1)
        responses, new_estado = handle_waiting_for_payment_date("549123", estado, "15-05-2025", member_service, "msg1")

        assert new_estado["estado"] == "esperando_confirmacion"
        split = new_estado["expense_data"]["split_strategy"]
        assert split["percentages"][1] == 0
        assert split["percentages"][2] == 100

    def test_three_members_transitions_to_recipient_state(self):
        """3-member loan: bot must ask who receives; state → esperando_destinatario_prestamo."""
        member_service = MagicMock()
        member_service.list_members.return_value = [
            _make_member(1, "Alice"),
            _make_member(2, "Bob"),
            _make_member(3, "Carol"),
        ]
        member_service.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol"}[mid]

        estado = _base_estado(service="prestar plata", payer_id=1)
        responses, new_estado = handle_waiting_for_payment_date("549123", estado, "15-05-2025", member_service, "msg1")

        assert new_estado["estado"] == "esperando_destinatario_prestamo"
        assert len(responses) == 1


class TestHandleWaitingForLoanRecipient:
    def test_valid_recipient_builds_split_and_confirms(self):
        """After recipient is selected, split is wired and confirmation is shown."""
        member_service = MagicMock()
        member_service.get_member_id_by_name.return_value = 3
        member_service.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 3: "Carol"}[mid]
        member_service.get_member_names.return_value = {1: "Alice", 3: "Carol"}

        estado = {
            "estado": "esperando_destinatario_prestamo",
            "expense_data": {
                "service": "prestar plata",
                "payer_id": 1,
                "description": "prestamo",
                "amount": 500.0,
                "date": "2025-05-15",
                "installments": 1,
            },
        }
        responses, new_estado = handle_waiting_for_loan_recipient("549123", estado, "Carol", member_service)

        assert new_estado["estado"] == "esperando_confirmacion"
        split = new_estado["expense_data"]["split_strategy"]
        assert split["percentages"][1] == 0
        assert split["percentages"][3] == 100

    def test_unknown_recipient_keeps_state_and_returns_error(self):
        """Unrecognised recipient name sends an error without changing state."""
        member_service = MagicMock()
        member_service.get_member_id_by_name.return_value = None

        estado = {"estado": "esperando_destinatario_prestamo", "expense_data": {"payer_id": 1}}
        responses, new_estado = handle_waiting_for_loan_recipient("549123", estado, "Nobody", member_service)

        assert new_estado["estado"] == "esperando_destinatario_prestamo"
        assert len(responses) == 1


class TestHandleWaitingForSplitStrategyNMembers:
    def test_two_members_porcentaje_goes_to_esperando_porcentaje(self):
        """2-member path: asking for payer's single percentage."""
        member_service = MagicMock()
        member_service.list_members.return_value = [_make_member(1, "Alice"), _make_member(2, "Bob")]

        estado = _base_estado(payer_id=1)
        estado["estado"] = "esperando_estrategia"

        _, new_estado = handle_waiting_for_split_strategy("549123", estado, "msg1", "📊 Porcentajes", member_service)
        assert new_estado["estado"] == "esperando_porcentaje"

    def test_three_members_porcentaje_goes_to_esperando_porcentaje_para_miembro(self):
        """3-member path: iterate over non-payer percentages."""
        member_service = MagicMock()
        member_service.list_members.return_value = [
            _make_member(1, "Alice"),
            _make_member(2, "Bob"),
            _make_member(3, "Carol"),
        ]
        member_service.get_member_name_by_id.return_value = "Bob"

        estado = _base_estado(payer_id=1)
        estado["estado"] = "esperando_estrategia"

        _, new_estado = handle_waiting_for_split_strategy("549123", estado, "msg1", "📊 Porcentajes", member_service)
        assert new_estado["estado"] == "esperando_porcentaje_para_miembro"
        assert new_estado["expense_data"]["remaining_member_ids"] == [2, 3]
        assert new_estado["expense_data"]["pending_percentages"] == {}


class TestHandleWaitingForPercentageForMember:
    def test_first_of_two_non_payers_prompts_for_second(self):
        """After entering Bob's %, Carol's % is requested; state stays iterating."""
        member_service = MagicMock()
        member_service.get_member_name_by_id.return_value = "Carol"

        estado = {
            "estado": "esperando_porcentaje_para_miembro",
            "expense_data": {
                "payer_id": 1,
                "remaining_member_ids": [2, 3],
                "pending_percentages": {},
                "description": "test",
                "amount": 100.0,
                "date": "2025-05-15",
                "installments": 1,
            },
        }
        _, new_estado = handle_waiting_for_percentage_for_member("549123", estado, "40", "msg1", member_service)

        assert new_estado["estado"] == "esperando_porcentaje_para_miembro"
        assert new_estado["expense_data"]["pending_percentages"] == {2: 40.0}
        assert new_estado["expense_data"]["remaining_member_ids"] == [3]

    def test_last_non_payer_finalizes_split_with_correct_payer_share(self):
        """After all non-payers entered, payer gets the remainder; state → esperando_confirmacion."""
        member_service = MagicMock()
        member_service.get_member_names.return_value = {1: "Alice", 2: "Bob", 3: "Carol"}
        member_service.get_member_name_by_id.side_effect = lambda mid: {1: "Alice", 2: "Bob", 3: "Carol"}[mid]

        estado = {
            "estado": "esperando_porcentaje_para_miembro",
            "expense_data": {
                "payer_id": 1,
                "remaining_member_ids": [3],
                "pending_percentages": {2: 40.0},
                "description": "test",
                "amount": 100.0,
                "date": "2025-05-15",
                "category": "comida",
                "payment_type": "debito",
                "installments": 1,
            },
        }
        _, new_estado = handle_waiting_for_percentage_for_member("549123", estado, "35", "msg1", member_service)

        assert new_estado["estado"] == "esperando_confirmacion"
        split = new_estado["expense_data"]["split_strategy"]
        assert split["percentages"][1] == 25.0  # 100 - 40 - 35
        assert split["percentages"][2] == 40.0
        assert split["percentages"][3] == 35.0
        assert "remaining_member_ids" not in new_estado["expense_data"]
        assert "pending_percentages" not in new_estado["expense_data"]

    def test_percentages_exceed_100_returns_error(self):
        """If entered percentages would exceed 100%, an error is returned."""
        member_service = MagicMock()
        member_service.get_member_name_by_id.return_value = "Carol"

        estado = {
            "estado": "esperando_porcentaje_para_miembro",
            "expense_data": {
                "payer_id": 1,
                "remaining_member_ids": [3],
                "pending_percentages": {2: 80.0},
                "description": "test",
                "amount": 100.0,
                "date": "2025-05-15",
                "category": "comida",
                "payment_type": "debito",
                "installments": 1,
            },
        }
        responses, new_estado = handle_waiting_for_percentage_for_member("549123", estado, "30", "msg1", member_service)

        assert new_estado["estado"] == "esperando_porcentaje_para_miembro"
        assert len(responses) == 1


class TestHandleWaitingForPercentageTwoMember:
    def test_percentage_dynamically_resolves_non_payer(self):
        """2-member percentage no longer uses hardcoded id=1/id=2 ternary."""
        member_service = MagicMock()
        member_service.list_members.return_value = [_make_member(3, "Tester"), _make_member(7, "Other")]
        member_service.get_member_names.return_value = {3: "Tester", 7: "Other"}
        member_service.get_member_name_by_id.side_effect = lambda mid: {3: "Tester", 7: "Other"}[mid]

        estado = {
            "estado": "esperando_porcentaje",
            "expense_data": {
                "payer_id": 3,
                "description": "test",
                "amount": 100.0,
                "date": "2025-05-15",
                "category": "comida",
                "payment_type": "debito",
                "installments": 1,
            },
        }
        _, new_estado = handle_waiting_for_percentage("549123", estado, "60", member_service)

        split = new_estado["expense_data"]["split_strategy"]
        assert split["percentages"][3] == 60.0
        assert split["percentages"][7] == 40.0
        assert new_estado["estado"] == "esperando_confirmacion"
