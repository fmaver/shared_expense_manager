"""Falling back to Claude when Gemini is overloaded.

Gemini occasionally answers 503 UNAVAILABLE ("high demand ... try again later"). That is a
transient capacity problem, not a problem with the image, so the same picture is retried on
Claude rather than told the user it could not be read.

Only overload falls back. A missing key, a malformed image or "no amount in this receipt" are
answers, not outages, and retrying them on a second paid model would burn money to reach the
same conclusion.
"""

from datetime import date
from unittest.mock import patch

import pytest

from template.service_layer.image_expense_parser import (
    ParsedImageExpense,
    parse_image_expense,
)

CATEGORIES = ["comida", "supermercado", "otros"]
PNG = "image/png"


class _Overloaded(Exception):
    """Stands in for the google-genai 503."""

    def __init__(self):
        super().__init__(
            "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
            "experiencing high demand.', 'status': 'UNAVAILABLE'}}"
        )


def _claude_result() -> ParsedImageExpense:
    return ParsedImageExpense(
        amount=1234.0,
        description="Coto",
        category="supermercado",
        expense_date=date(2026, 9, 5),
        payment_type="debit",
        confidence="high",
        installments=1,
        currency="ARS",
    )


def test_gemini_503_falls_back_to_claude():
    """The whole point: a capacity blip should not lose the user's screenshot."""
    with (
        patch("template.service_layer.image_expense_parser._parse_with_gemini", side_effect=_Overloaded()),
        patch(
            "template.service_layer.image_expense_parser._parse_with_claude",
            return_value=_claude_result(),
        ) as claude,
    ):
        result = parse_image_expense(b"img", PNG, CATEGORIES)

    claude.assert_called_once()
    assert result is not None
    assert result.amount == 1234.0


def test_a_successful_gemini_read_never_calls_claude():
    """Claude is the backup, not a second opinion — calling both would double the bill."""
    with (
        patch(
            "template.service_layer.image_expense_parser._parse_with_gemini",
            return_value=_claude_result(),
        ),
        patch("template.service_layer.image_expense_parser._parse_with_claude") as claude,
    ):
        parse_image_expense(b"img", PNG, CATEGORIES)

    claude.assert_not_called()


def test_gemini_returning_none_does_not_fall_back():
    """None means Gemini read the image and found no expense — a second model would agree."""
    with (
        patch("template.service_layer.image_expense_parser._parse_with_gemini", return_value=None),
        patch("template.service_layer.image_expense_parser._parse_with_claude") as claude,
    ):
        assert parse_image_expense(b"img", PNG, CATEGORIES) is None

    claude.assert_not_called()


def test_a_non_overload_error_does_not_fall_back():
    """A malformed image fails on both; retrying spends money to fail twice."""
    with (
        patch(
            "template.service_layer.image_expense_parser._parse_with_gemini",
            side_effect=ValueError("invalid image data"),
        ),
        patch("template.service_layer.image_expense_parser._parse_with_claude") as claude,
    ):
        assert parse_image_expense(b"img", PNG, CATEGORIES) is None

    claude.assert_not_called()


def test_both_failing_returns_none_rather_than_raising():
    """The caller shows a friendly message; it must never see an exception."""
    with (
        patch("template.service_layer.image_expense_parser._parse_with_gemini", side_effect=_Overloaded()),
        patch(
            "template.service_layer.image_expense_parser._parse_with_claude",
            side_effect=RuntimeError("claude down too"),
        ),
    ):
        assert parse_image_expense(b"img", PNG, CATEGORIES) is None


@pytest.mark.parametrize(
    "message",
    [
        "503 UNAVAILABLE. {'error': {'code': 503}}",
        "The model is overloaded. Please try again later.",
        "429 RESOURCE_EXHAUSTED",
    ],
)
def test_recognises_the_shapes_capacity_errors_arrive_in(message):
    """google-genai does not expose a typed 503, so detection is on the message."""
    from template.service_layer.image_expense_parser import _is_capacity_error

    assert _is_capacity_error(Exception(message)) is True


def test_does_not_mistake_an_ordinary_error_for_overload():
    from template.service_layer.image_expense_parser import _is_capacity_error

    assert _is_capacity_error(ValueError("invalid image data")) is False


def test_an_unsupported_media_type_does_not_reach_claude():
    """Claude takes only jpeg/png/gif/webp. An iPhone photo can be image/heic, which Gemini
    tolerates — sending it anyway would just trade one failure for another."""
    from template.service_layer.image_expense_parser import _parse_with_claude

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        assert _parse_with_claude(b"img", "image/heic", CATEGORIES, date(2026, 9, 5)) is None
