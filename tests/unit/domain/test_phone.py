"""Unit tests for Argentine phone-number normalization."""

import pytest

from template.domain.phone import normalize_ar_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The reported bug: a stray mobile "9" after the country code is dropped.
        ("5491133334444", "541133334444"),
        # Already canonical → unchanged (idempotent).
        ("541133334444", "541133334444"),
        # Formatted input (like the ProfilePage display) collapses to canonical.
        ("+54 9 11 3333-4444", "541133334444"),
        ("+5411 3333 4444", "541133334444"),
        # Local input with the trunk 0 and no country code.
        ("01133334444", "541133334444"),
        # Bare local number, no country code, no trunk.
        ("1133334444", "541133334444"),
        # International access prefix.
        ("00541133334444", "541133334444"),
        # Local with the mobile 9 but no country code.
        ("91133334444", "541133334444"),
    ],
)
def test_normalizes_to_canonical_54(raw, expected):
    assert normalize_ar_phone(raw) == expected


def test_none_returns_none():
    assert normalize_ar_phone(None) is None


@pytest.mark.parametrize("blank", ["", "   ", "+", "()- "])
def test_blank_returns_none(blank):
    assert normalize_ar_phone(blank) is None


def test_is_idempotent():
    once = normalize_ar_phone("5491133334444")
    assert normalize_ar_phone(once) == once
