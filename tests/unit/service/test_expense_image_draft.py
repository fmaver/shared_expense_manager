"""Turning an uploaded screenshot into an expense draft.

The image is read by an LLM (Gemini Vision), which shapes everything here: it is slow, it costs
money per call, and it is sometimes wrong. So the result is a *draft* for the user to confirm —
never a written expense — and anything obviously not worth sending is rejected before the call
is made rather than after.
"""

from datetime import date
from unittest.mock import patch

import pytest

from template.service_layer.expense_draft_service import (
    MAX_IMAGE_BYTES,
    build_expense_draft,
)
from template.service_layer.image_expense_parser import ParsedImageExpense

PNG = "image/png"


def _parsed(**overrides) -> ParsedImageExpense:
    payload = {
        "amount": 4500.0,
        "description": "Coto",
        "category": "supermercado",
        "expense_date": date(2026, 9, 5),
        "payment_type": "debit",
        "confidence": "high",
        "installments": 1,
        "currency": "ARS",
    }
    payload.update(overrides)
    return ParsedImageExpense(**payload)


# ---------------------------------------------------------------------------
# Rejected before the model is ever called
# ---------------------------------------------------------------------------


def test_rejects_a_non_image():
    """A PDF or a text file would burn an LLM call to fail."""
    with patch("template.service_layer.expense_draft_service.parse_image_expense") as parser:
        with pytest.raises(ValueError):
            build_expense_draft(b"%PDF-1.4", "application/pdf")
        parser.assert_not_called()


def test_rejects_an_oversized_image():
    """Guards latency and cost: the model is paid per call and slow on large inputs."""
    with patch("template.service_layer.expense_draft_service.parse_image_expense") as parser:
        with pytest.raises(ValueError):
            build_expense_draft(b"x" * (MAX_IMAGE_BYTES + 1), PNG)
        parser.assert_not_called()


def test_rejects_an_empty_upload():
    with patch("template.service_layer.expense_draft_service.parse_image_expense") as parser:
        with pytest.raises(ValueError):
            build_expense_draft(b"", PNG)
        parser.assert_not_called()


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


def test_maps_a_parsed_image_into_a_draft():
    with patch("template.service_layer.expense_draft_service.parse_image_expense", return_value=_parsed()):
        draft = build_expense_draft(b"fake-png-bytes", PNG)

    assert draft.amount == 4500.0
    assert draft.description == "Coto"
    assert draft.category == "supermercado"
    assert draft.date == date(2026, 9, 5)
    assert draft.payment_type == "debit"
    assert draft.installments == 1
    assert draft.currency == "ARS"
    assert draft.confidence == "high"


def test_low_confidence_is_passed_through_not_hidden():
    """The UI needs to know when to be sceptical; swallowing this would be dishonest."""
    with patch(
        "template.service_layer.expense_draft_service.parse_image_expense",
        return_value=_parsed(confidence="low", amount=None),
    ):
        draft = build_expense_draft(b"fake", PNG)

    assert draft.confidence == "low"
    assert draft.amount is None


def test_raises_when_the_model_cannot_parse():
    """parse_image_expense returns None for a missing API key, a network error or no amount."""
    with patch("template.service_layer.expense_draft_service.parse_image_expense", return_value=None):
        with pytest.raises(ValueError):
            build_expense_draft(b"fake", PNG)


def test_credit_with_installments_survives():
    """Cuotas read off a screenshot are the whole point of parsing it."""
    with patch(
        "template.service_layer.expense_draft_service.parse_image_expense",
        return_value=_parsed(payment_type="credit", installments=6, amount=60000.0),
    ):
        draft = build_expense_draft(b"fake", PNG)

    assert draft.payment_type == "credit"
    assert draft.installments == 6


def test_the_categories_sent_to_the_model_exclude_internal_ones():
    """balance and prestamo are internal; offering them would let the model pick one."""
    with patch("template.service_layer.expense_draft_service.parse_image_expense", return_value=_parsed()) as parser:
        build_expense_draft(b"fake", PNG)

    categories = parser.call_args[0][2]
    assert "balance" not in categories
    assert "prestamo" not in categories
    assert "supermercado" in categories
