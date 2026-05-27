"""Unit tests for image_expense_parser — Gemini API is mocked."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.service_layer.image_expense_parser import (
    ParsedImageExpense,
    parse_image_expense,
)

CATEGORIES = ["comida", "supermercado", "entretenimiento", "servicios", "transporte", "viajes", "salud", "otros"]
TODAY = date(2026, 5, 27)
FAKE_BYTES = b"\xff\xd8\xff"  # minimal JPEG header


def _mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    return resp


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")


class TestParseImageExpense:
    def test_happy_path_high_confidence(self):
        json_str = (
            '{"amount": 1500.0, "description": "Coto Palermo", "date": "2026-05-27",'
            ' "category": "supermercado", "payment_type": "debit", "confidence": "high"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.amount == 1500.0
        assert result.description == "Coto Palermo"
        assert result.category == "supermercado"
        assert result.payment_type == "debit"
        assert result.confidence == "high"
        assert result.expense_date == TODAY

    def test_low_confidence_still_returns(self):
        json_str = (
            '{"amount": 800.0, "description": "Gasto", "date": "2026-05-27",'
            ' "category": "otros", "payment_type": "debit", "confidence": "low"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.confidence == "low"

    def test_missing_amount_returns_none(self):
        json_str = (
            '{"amount": null, "description": "Unknown", "date": "2026-05-27",'
            ' "category": "otros", "payment_type": "debit", "confidence": "low"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is None

    def test_unknown_category_falls_back_to_otros(self):
        json_str = (
            '{"amount": 500.0, "description": "XYZ Store", "date": "2026-05-27",'
            ' "category": "compras", "payment_type": "debit", "confidence": "low"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.category == "otros"

    def test_invalid_date_falls_back_to_today(self):
        json_str = (
            '{"amount": 300.0, "description": "Rest", "date": "not-a-date",'
            ' "category": "comida", "payment_type": "debit", "confidence": "low"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.expense_date == TODAY

    def test_missing_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)
        assert result is None

    def test_gemini_api_error_returns_none(self):
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.side_effect = Exception("API unavailable")
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is None

    def test_empty_response_returns_none(self):
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response("")
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is None

    def test_strips_markdown_fences(self):
        json_str = (
            '```json\n{"amount": 250.0, "description": "Farmacia", "date": "2026-05-27",'
            ' "category": "salud", "payment_type": "debit", "confidence": "high"}\n```'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.amount == 250.0

    def test_credit_payment_type(self):
        json_str = (
            '{"amount": 12000.0, "description": "Falabella", "date": "2026-05-27",'
            ' "category": "entretenimiento", "payment_type": "credit", "confidence": "high"}'
        )
        with patch("google.genai.Client") as mock_genai:
            mock_genai.return_value.models.generate_content.return_value = _mock_response(json_str)
            result = parse_image_expense(FAKE_BYTES, "image/jpeg", CATEGORIES, TODAY)

        assert result is not None
        assert result.payment_type == "credit"
