"""Unit tests for picking the past months that were left unsettled."""

from datetime import date

from template.domain.models.models import MonthlyShare
from template.service_layer.unsettled_months import unsettled_periods


def _share(year, month, balances, settled=False):
    share = MonthlyShare(year, month, group_id=1)
    share.balances = balances
    if settled:
        share.settle()
    return share


TODAY = date(2026, 9, 27)


def test_past_unsettled_month_with_balance_is_listed():
    shares = [_share(2026, 7, {"1": 500.0, "2": -500.0})]
    assert unsettled_periods(shares, TODAY) == [(2026, 7)]


def test_current_and_future_months_are_never_listed():
    shares = [_share(2026, 9, {"1": 10.0, "2": -10.0}), _share(2026, 11, {"1": 10.0, "2": -10.0})]
    assert unsettled_periods(shares, TODAY) == []


def test_settled_month_is_not_listed():
    assert unsettled_periods([_share(2026, 6, {"1": 10.0, "2": -10.0}, settled=True)], TODAY) == []


def test_all_square_month_is_not_listed():
    assert unsettled_periods([_share(2026, 5, {"1": 0.004, "2": -0.004})], TODAY) == []


def test_sorted_oldest_first_across_years():
    shares = [_share(2026, 3, {"1": 5.0}), _share(2025, 12, {"1": -5.0}), _share(2026, 8, {"2": 1.0})]
    assert unsettled_periods(shares, TODAY) == [(2025, 12), (2026, 3), (2026, 8)]
