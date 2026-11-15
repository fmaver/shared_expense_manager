"""The parser reads amounts and dates from the text printed on the receipt, not the model's float.

A model asked for a float misreads Argentine thousands separators: "2.282.578,45" came back as
2282.57 on some reads and 2282578.45 on others, from the same screenshot. Dates printed as
"12/11/26" came back as three different days. Parsing the printed text in code makes the same
image give the same expense every time.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.service_layer.image_expense_parser import (
    _build_prompt,
    parse_amount_text,
    parse_date_text,
    parse_image_expense,
)

CATEGORIES = ["comida", "supermercado", "servicios", "otros"]
TODAY = date(2026, 11, 15)


class TestParseAmountText:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("2.282.578,45", 2282578.45),
            ("$ 2.282.578,45", 2282578.45),
            ("$2.500", 2500.0),
            ("1.500", 1500.0),
            ("1.500,5", 1500.5),
            ("42.300,00", 42300.0),
            ("5000", 5000.0),
            ("1500,50", 1500.5),
            ("US$ 1,234.56", 1234.56),
            ("12.5", 12.5),
            ("-$ 3.000", 3000.0),
        ],
    )
    def test_reads_argentine_and_us_formats(self, text, expected):
        assert parse_amount_text(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "   ", "total", None])
    def test_unreadable_text_is_none(self, text):
        assert parse_amount_text(text) is None


class TestParseDateText:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("12/11/26", date(2026, 11, 12)),
            ("12/11/2026", date(2026, 11, 12)),
            ("1/3/2026", date(2026, 3, 1)),
            ("12-11-2026", date(2026, 11, 12)),
            ("2026-11-12", date(2026, 11, 12)),
            ("Fecha de Pago 12/11/26", date(2026, 11, 12)),
        ],
    )
    def test_reads_day_first(self, text, expected):
        assert parse_date_text(text, TODAY) == expected

    @pytest.mark.parametrize("text", ["", None, "ayer", "31/02/2026"])
    def test_unreadable_text_is_none(self, text):
        assert parse_date_text(text, TODAY) is None

    def test_future_date_is_rejected(self):
        assert parse_date_text("20/12/2026", TODAY) is None


def _gemini_returns(json_str: str):
    resp = MagicMock()
    resp.text = json_str
    patcher = patch("google.genai.Client")
    mock_genai = patcher.start()
    mock_genai.return_value.models.generate_content.return_value = resp
    return patcher, mock_genai


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")


class TestPrintedTextWins:
    def test_amount_text_overrides_a_misread_float(self):
        patcher, _ = _gemini_returns(
            '{"amount": 2282.57, "amount_text": "2.282.578,45", "description": "Santander",'
            ' "date": "2026-11-12", "date_text": "12/11/26", "category": "servicios",'
            ' "payment_type": "debit", "installments": 1, "confidence": "high", "currency": "ARS"}'
        )
        try:
            result = parse_image_expense(b"\xff\xd8\xff", "image/jpeg", CATEGORIES, TODAY)
        finally:
            patcher.stop()
        assert result is not None
        assert result.amount == pytest.approx(2282578.45)
        assert result.expense_date == date(2026, 11, 12)

    def test_falls_back_to_the_float_when_text_is_missing(self):
        patcher, _ = _gemini_returns(
            '{"amount": 1500.0, "description": "Coto", "date": "2026-11-10", "category": "supermercado",'
            ' "payment_type": "debit", "confidence": "high"}'
        )
        try:
            result = parse_image_expense(b"\xff\xd8\xff", "image/jpeg", CATEGORIES, TODAY)
        finally:
            patcher.stop()
        assert result is not None
        assert result.amount == 1500.0
        assert result.expense_date == date(2026, 11, 10)

    def test_future_model_date_falls_back_to_today(self):
        patcher, _ = _gemini_returns(
            '{"amount": 100, "description": "Kiosco", "date": "2026-12-26", "category": "comida",'
            ' "payment_type": "debit", "confidence": "low"}'
        )
        try:
            result = parse_image_expense(b"\xff\xd8\xff", "image/jpeg", CATEGORIES, TODAY)
        finally:
            patcher.stop()
        assert result is not None
        assert result.expense_date == TODAY

    def test_gemini_is_called_deterministically(self):
        patcher, mock_genai = _gemini_returns(
            '{"amount": 100, "description": "Kiosco", "date": "2026-11-10", "category": "comida",'
            ' "payment_type": "debit", "confidence": "low"}'
        )
        try:
            parse_image_expense(b"\xff\xd8\xff", "image/jpeg", CATEGORIES, TODAY)
        finally:
            patcher.stop()
        config = mock_genai.return_value.models.generate_content.call_args.kwargs["config"]
        assert config.temperature == 0


class TestPromptRules:
    def test_prompt_asks_for_the_printed_text_spanish_and_card_payments(self):
        prompt = _build_prompt(CATEGORIES, TODAY)
        assert '"amount_text"' in prompt
        assert '"date_text"' in prompt
        assert "DD/MM" in prompt
        assert "Spanish" in prompt and "never translate" in prompt
        assert "credit card statement" in prompt
