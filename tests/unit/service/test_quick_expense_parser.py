"""Unit tests for the quick_expense_parser module."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.service_layer.quick_expense_parser import (
    ParsedExpense,
    parse_quick_expense,
)

MEMBERS = [
    {"id": 1, "name": "Fran"},
    {"id": 2, "name": "Guada"},
]
CATEGORIES = [
    "auto",
    "casa",
    "salidas",
    "supermercado",
    "mascota",
    "entretenimiento",
    "shopping",
    "viajes",
    "salud",
    "otros",
]
TODAY = date(2026, 5, 26)


def _mock_response(payload: dict) -> MagicMock:
    """Build a fake Anthropic response containing a JSON string."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(payload))]
    return msg


def _make_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = _mock_response(payload)
    return client


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


class TestParseQuickExpense:
    def test_returns_none_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = parse_quick_expense("gasté $500", MEMBERS, CATEGORIES, 1, TODAY)
        assert result is None

    def test_returns_none_when_not_an_expense(self):
        payload = {"is_expense": False}
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("¿cómo estás?", MEMBERS, CATEGORIES, 1, TODAY)
        assert result is None

    def test_parses_basic_expense(self):
        payload = {
            "is_expense": True,
            "amount": 2000.0,
            "description": "super",
            "category": "supermercado",
            "payer_id": 1,
            "date": "2026-05-26",
            "payment_type": "debit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("gasté $2000 en el super", MEMBERS, CATEGORIES, 1, TODAY)

        assert isinstance(result, ParsedExpense)
        assert result.amount == 2000.0
        assert result.description == "super"
        assert result.category == "supermercado"
        assert result.payer_id == 1
        assert result.expense_date == date(2026, 5, 26)
        assert result.payment_type == "debit"
        assert result.installments == 1
        assert result.split_strategy is None

    def test_parses_third_person_payer(self):
        payload = {
            "is_expense": True,
            "amount": 500.0,
            "description": "farmacia",
            "category": "salud",
            "payer_id": 2,
            "date": "2026-05-26",
            "payment_type": "debit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("Guada pagó $500 en la farmacia", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.payer_id == 2

    def test_parses_credit_with_installments(self):
        payload = {
            "is_expense": True,
            "amount": 6000.0,
            "description": "heladera",
            "category": "otros",
            "payer_id": 1,
            "date": "2026-05-26",
            "payment_type": "credit",
            "installments": 3,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("compré una heladera en 3 cuotas por $6000", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.payment_type == "credit"
        assert result.installments == 3

    def test_cuotas_without_explicit_credito_implies_credit(self):
        """'pague en 3 cuotas' should be parsed as credit even without the word 'crédito'."""
        payload = {
            "is_expense": True,
            "amount": 5000.0,
            "description": "zapatillas",
            "category": "shopping",
            "payer_id": 1,
            "date": "2026-05-26",
            "payment_type": "credit",
            "installments": 3,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("pague zapatillas en 3 cuotas $5000", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.payment_type == "credit"
        assert result.installments == 3

    def test_cuotas_without_number_implies_credit_1_installment(self):
        """'pagué en cuotas' with no count should be credit with 1 installment."""
        payload = {
            "is_expense": True,
            "amount": 3000.0,
            "description": "ropa",
            "category": "shopping",
            "payer_id": 1,
            "date": "2026-05-26",
            "payment_type": "credit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("pagué ropa en cuotas $3000", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.payment_type == "credit"

    def test_returns_none_on_llm_exception(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("network error")
        with patch("anthropic.Anthropic", return_value=client):
            result = parse_quick_expense("gasté $100", MEMBERS, CATEGORIES, 1, TODAY)
        assert result is None

    def test_returns_none_on_invalid_json(self):
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text="not valid json {{")]
        client = MagicMock()
        client.messages.create.return_value = bad_msg
        with patch("anthropic.Anthropic", return_value=client):
            result = parse_quick_expense("gasté $100", MEMBERS, CATEGORIES, 1, TODAY)
        assert result is None

    def test_uses_today_as_default_date(self):
        payload = {
            "is_expense": True,
            "amount": 300.0,
            "description": "kiosco",
            "category": "otros",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("gasté $300 en el kiosco", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.expense_date == TODAY

    def test_expense_is_not_a_loan(self):
        payload = {
            "is_expense": True,
            "is_loan": False,
            "amount": 1000.0,
            "description": "super",
            "category": "supermercado",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("gasté $1000 en el super", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.is_loan is False
        assert result.recipient_id is None


class TestParseQuickLoan:
    def test_parses_first_person_loan(self):
        payload = {
            "is_expense": True,
            "is_loan": True,
            "amount": 12000.0,
            "description": "préstamo a Guada",
            "payer_id": 1,
            "recipient_id": 2,
            "date": "2026-05-25",
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("le presté 12000 pesos a Guada", MEMBERS, CATEGORIES, 1, TODAY)

        assert isinstance(result, ParsedExpense)
        assert result.is_loan is True
        assert result.amount == 12000.0
        assert result.payer_id == 1
        assert result.recipient_id == 2
        assert result.category == "prestamo"
        assert result.payment_type == "debito"
        assert result.installments == 1

    def test_parses_third_person_loan(self):
        payload = {
            "is_expense": True,
            "is_loan": True,
            "amount": 5000.0,
            "description": "préstamo a Fran",
            "payer_id": 2,
            "recipient_id": 1,
            "date": TODAY.isoformat(),
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("Guada le prestó $5000 a Fran", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.is_loan is True
        assert result.payer_id == 2
        assert result.recipient_id == 1

    def test_parses_loan_with_yesterday_date(self):
        payload = {
            "is_expense": True,
            "is_loan": True,
            "amount": 12000.0,
            "description": "préstamo a Guada",
            "payer_id": 1,
            "recipient_id": 2,
            "date": "2026-05-25",
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("el lunes pasado le presté a Guada 12000", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.expense_date.isoformat() == "2026-05-25"

    def test_returns_none_when_recipient_id_missing(self):
        payload = {
            "is_expense": True,
            "is_loan": True,
            "amount": 1000.0,
            "description": "préstamo",
            "payer_id": 1,
            "date": TODAY.isoformat(),
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("le presté plata a alguien", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.is_loan is True
        assert result.recipient_id is None


class TestParseQuickExpenseSplitStrategy:
    def test_no_split_mentioned_returns_none_split_strategy(self):
        """When no split is mentioned the field should be None (bot defaults to equal)."""
        payload = {
            "is_expense": True,
            "amount": 1000.0,
            "description": "supermercado",
            "category": "supermercado",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("gasté $1000 en el super", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.split_strategy is None

    def test_explicit_equal_split(self):
        """'a partes iguales' → split_strategy type equal."""
        payload = {
            "is_expense": True,
            "amount": 2000.0,
            "description": "cena",
            "category": "salidas",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
            "split_strategy": {"type": "equal"},
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense("salí a comer $2000 a partes iguales", MEMBERS, CATEGORIES, 1, TODAY)

        assert result is not None
        assert result.split_strategy == {"type": "equal"}

    def test_exact_amounts_split(self):
        """'me corresponden X y a Guada Y' → exact split with per-member amounts."""
        payload = {
            "is_expense": True,
            "amount": 2000.0,
            "description": "supermercado",
            "category": "supermercado",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
            "split_strategy": {"type": "exact", "amounts": {"1": 1500, "2": 500}},
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense(
                "Pague 2000 en supermercado, me corresponden 1500 y a Guada 500",
                MEMBERS,
                CATEGORIES,
                1,
                TODAY,
            )

        assert result is not None
        assert result.split_strategy is not None
        assert result.split_strategy["type"] == "exact"
        amounts = result.split_strategy["amounts"]
        assert amounts["1"] == 1500
        assert amounts["2"] == 500

    def test_percentage_split(self):
        """'me corresponde el 70% y a Guada el 30%' → percentage split."""
        payload = {
            "is_expense": True,
            "amount": 5000.0,
            "description": "alquiler",
            "category": "casa",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
            "split_strategy": {"type": "percentage", "percentages": {"1": 70, "2": 30}},
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense(
                "pagué el alquiler $5000, me corresponde el 70% y a Guada el 30%",
                MEMBERS,
                CATEGORIES,
                1,
                TODAY,
            )

        assert result is not None
        assert result.split_strategy is not None
        assert result.split_strategy["type"] == "percentage"
        pcts = result.split_strategy["percentages"]
        assert pcts["1"] == 70
        assert pcts["2"] == 30

    def test_equal_subset_split(self):
        """'entre Fran y Guada' with extra members → equal with participant_ids subset."""
        members_3 = [
            {"id": 1, "name": "Fran"},
            {"id": 2, "name": "Guada"},
            {"id": 3, "name": "Pedro"},
        ]
        payload = {
            "is_expense": True,
            "amount": 3000.0,
            "description": "cena",
            "category": "salidas",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
            "split_strategy": {"type": "equal", "participant_ids": [1, 2]},
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense(
                "pagué $3000 de cena entre Fran y Guada",
                members_3,
                CATEGORIES,
                1,
                TODAY,
            )

        assert result is not None
        assert result.split_strategy is not None
        assert result.split_strategy["type"] == "equal"
        assert result.split_strategy["participant_ids"] == [1, 2]

    def test_exact_split_implies_excludes_non_mentioned_members(self):
        """Exact split with only 2 of 3 members means the third is excluded (0 share)."""
        members_3 = [
            {"id": 1, "name": "Fran"},
            {"id": 2, "name": "Guada"},
            {"id": 3, "name": "Pedro"},
        ]
        payload = {
            "is_expense": True,
            "amount": 2000.0,
            "description": "supermercado",
            "category": "supermercado",
            "payer_id": 1,
            "date": TODAY.isoformat(),
            "payment_type": "debit",
            "installments": 1,
            "split_strategy": {"type": "exact", "amounts": {"1": 1500, "2": 500}},
        }
        with patch("anthropic.Anthropic", return_value=_make_client(payload)):
            result = parse_quick_expense(
                "Pague 2000 en super, me corresponden 1500 y a Guada 500",
                members_3,
                CATEGORIES,
                1,
                TODAY,
            )

        assert result is not None
        assert result.split_strategy["type"] == "exact"
        amounts = result.split_strategy["amounts"]
        # Pedro (id=3) is not mentioned → not in amounts dict
        assert "3" not in amounts
        assert amounts["1"] == 1500
        assert amounts["2"] == 500
