"""Unit tests for the search query parser — no DB."""

import pytest

from template.service_layer.search_query import (
    ParsedQuery,
    normalize,
    parse_amount,
    parse_query,
)


def test_normalize_lowercases_and_strips_accents():
    assert normalize("Café Ñandú ÁRBOL") == "cafe nandu arbol"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("24000", 24000.0),
        ("24.000", 24000.0),
        ("24000,50", 24000.5),
        ("24.000,50", 24000.5),
        ("1.234.567", 1234567.0),
        ("1.5", 1.5),
        ("1.50", 1.5),
        ("0", 0.0),
        ("cena", None),
        ("24k", None),
        ("", None),
        ("1.2345", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_query_splits_words_and_normalizes():
    assert parse_query("  Cena   en el Centro ") == ParsedQuery(terms=("cena", "en", "el", "centro"), amount=None)


def test_parse_query_number_keeps_text_term_and_amount():
    assert parse_query("24.000") == ParsedQuery(terms=("24.000",), amount=24000.0)


def test_parse_query_too_short_returns_none():
    assert parse_query("a") is None
    assert parse_query("   ") is None


def test_parse_query_single_digit_number_is_allowed():
    assert parse_query("5") == ParsedQuery(terms=("5",), amount=5.0)
