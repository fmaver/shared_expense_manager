"""Tests for WhatsApp chatbot handlers related to recurring group expenses."""

import json
from unittest.mock import MagicMock

from template.service_layer.whatsapp_service import (
    handle_gastos_recurrentes,
    handle_waiting_for_recurrencia,
    handle_waiting_for_recurring_delete_confirmation,
)


def _decode(data: str) -> dict:
    return json.loads(data)


def _make_template(tid: int, description: str, amount: float):
    t = MagicMock()
    t.id = tid
    t.description = description
    t.amount = amount
    return t


def _base_recurrencia_estado():
    return {
        "estado": "esperando_recurrencia",
        "expense_data": {
            "service": "cargar gasto",
            "payer_id": 1,
            "description": "almuerzo",
            "amount": 500.0,
            "date": "2025-06-01",
            "category": "comida",
            "payment_type": "debito",
            "installments": 1,
            "split_strategy": {"type": "equal"},
        },
    }


def _base_delete_estado(template_id: int = 42, description: str = "Gym"):
    return {
        "estado": "esperando_confirmacion_eliminar_recurrente",
        "expense_data": {
            "service": "cargar gasto",
            "selected_recurring_id": template_id,
            "selected_recurring_description": description,
        },
    }


# ---------------------------------------------------------------------------
# handle_waiting_for_recurrencia
# ---------------------------------------------------------------------------


class TestHandleWaitingForRecurrenciaMensual:
    def test_interactive_id_btn_1_sets_recurring_true(self):
        """sed_recur_btn_1 → is_recurring True."""
        service = MagicMock()
        service.find_similar_expenses.return_value = []
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        estado = _base_recurrencia_estado()
        _, new = handle_waiting_for_recurrencia("549123", estado, "", "sed_recur_btn_1", service, ms)

        assert new["expense_data"]["is_recurring"] is True

    def test_text_repite_sets_recurring_true(self):
        """Free-text containing 'repite' also sets is_recurring True."""
        service = MagicMock()
        service.find_similar_expenses.return_value = []
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        estado = _base_recurrencia_estado()
        _, new = handle_waiting_for_recurrencia("549123", estado, "Repite cada mes", None, service, ms)

        assert new["expense_data"]["is_recurring"] is True


class TestHandleWaitingForRecurrenciaUnaVez:
    def test_interactive_id_btn_2_sets_recurring_false(self):
        """sed_recur_btn_2 → is_recurring False."""
        service = MagicMock()
        service.find_similar_expenses.return_value = []
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        estado = _base_recurrencia_estado()
        _, new = handle_waiting_for_recurrencia("549123", estado, "", "sed_recur_btn_2", service, ms)

        assert new["expense_data"]["is_recurring"] is False

    def test_non_recurring_text_sets_recurring_false(self):
        """Text without recurring keywords sets is_recurring False."""
        service = MagicMock()
        service.find_similar_expenses.return_value = []
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        estado = _base_recurrencia_estado()
        _, new = handle_waiting_for_recurrencia("549123", estado, "Una sola vez", None, service, ms)

        assert new["expense_data"]["is_recurring"] is False


# ---------------------------------------------------------------------------
# handle_gastos_recurrentes
# ---------------------------------------------------------------------------


class TestHandleGastosRecurrentesEmpty:
    def test_empty_list_returns_no_tenets_message(self):
        """When repo returns no templates, reply with 'no tenés gastos recurrentes'."""
        repo = MagicMock()
        repo.list_for_group.return_value = []

        estado = {"estado": "inicial", "expense_data": {}}
        responses, new = handle_gastos_recurrentes("549123", estado, repo, group_id=1)

        assert new["estado"] == "inicial"
        assert len(responses) == 1
        body = _decode(responses[0])
        assert "recurrentes" in body["text"]["body"].lower()


class TestHandleGastosRecurrentesWithTemplates:
    def test_two_templates_returns_interactive_reply(self):
        """When repo returns 2 templates, send an interactive selector."""
        repo = MagicMock()
        repo.list_for_group.return_value = [
            _make_template(1, "Gym", 5000.0),
            _make_template(2, "Netflix", 1500.0),
        ]

        estado = {"estado": "inicial", "expense_data": {}}
        responses, new = handle_gastos_recurrentes("549123", estado, repo, group_id=1)

        assert new["estado"] == "esperando_seleccion_recurrente"
        assert len(responses) == 1

        # The message should be interactive (button or list)
        data = _decode(responses[0])
        assert data["type"] == "interactive"

    def test_two_templates_stores_them_in_expense_data(self):
        """Template list is persisted in expense_data for later selection."""
        repo = MagicMock()
        repo.list_for_group.return_value = [
            _make_template(10, "Gym", 5000.0),
            _make_template(20, "Netflix", 1500.0),
        ]

        estado = {"estado": "inicial", "expense_data": {}}
        _, new = handle_gastos_recurrentes("549123", estado, repo, group_id=1)

        stored = new["expense_data"]["recurring_templates"]
        assert len(stored) == 2
        assert stored[0]["id"] == 10
        assert stored[1]["id"] == 20


# ---------------------------------------------------------------------------
# handle_waiting_for_recurring_delete_confirmation
# ---------------------------------------------------------------------------


class TestHandleWaitingForRecurringDeleteConfirmationYes:
    def _repo(self):
        return MagicMock()

    def test_confirm_button_calls_deactivate_and_delete_instances(self):
        """Confirming deletion calls deactivate AND delete_instances_from_month_onwards."""
        repo = self._repo()
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"

        estado = _base_delete_estado(template_id=42)
        _, new = handle_waiting_for_recurring_delete_confirmation("549123", estado, "", "sed_recur_del_btn_1", repo, ms)

        repo.deactivate.assert_called_once_with(42)
        repo.delete_instances_from_month_onwards.assert_called_once()
        # The call should pass template_id=42 as first positional arg
        call_args = repo.delete_instances_from_month_onwards.call_args[0]
        assert call_args[0] == 42

    def test_text_eliminar_also_confirms_deletion(self):
        """Free-text 'eliminar' also triggers deactivation."""
        repo = self._repo()
        ms = MagicMock()

        estado = _base_delete_estado(template_id=7)
        handle_waiting_for_recurring_delete_confirmation("549123", estado, "eliminar", None, repo, ms)

        repo.deactivate.assert_called_once_with(7)
        repo.delete_instances_from_month_onwards.assert_called_once()

    def test_confirm_resets_state_to_inicial(self):
        """After confirmation state should be cleaned up (back to inicial or clean)."""
        repo = self._repo()
        ms = MagicMock()

        estado = _base_delete_estado(template_id=42)
        _, new = handle_waiting_for_recurring_delete_confirmation("549123", estado, "", "sed_recur_del_btn_1", repo, ms)

        # State should be reset (clean_estado_usuario sets many fields to None)
        assert new["estado"] == "inicial"

    def test_cancel_does_not_call_deactivate(self):
        """Pressing cancel leaves the template untouched."""
        repo = self._repo()
        ms = MagicMock()
        ms.get_member_name_by_id.return_value = "Alice"
        ms.get_member_by_phone.return_value = None

        estado = _base_delete_estado(template_id=42)
        handle_waiting_for_recurring_delete_confirmation("549123", estado, "cancelar", None, repo, ms, groups=[])

        repo.deactivate.assert_not_called()
        repo.delete_instances_from_month_onwards.assert_not_called()
