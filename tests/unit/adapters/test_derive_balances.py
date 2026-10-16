"""SQLAlchemyExpenseRepository._derive_balances — how an open month's balances are computed on load."""

from datetime import date
from unittest.mock import MagicMock, patch

from template.adapters.repositories import SQLAlchemyExpenseRepository
from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.split import EqualSplit

MEMBERS = {1: Member(id=1, name="Guadi"), 2: Member(id=2, name="Marian")}


def _share(*expenses: Expense, stored: dict | None = None) -> MonthlyShare:
    share = MonthlyShare(2026, 10, 8)
    share.expenses = list(expenses)
    share.balances = dict(stored or {})
    return share


def _expense(amount: float, payer_id: int, currency: str = "ARS") -> Expense:
    category = Category()
    category.name = "otros"
    return Expense(
        id=1,
        description="x",
        amount=amount,
        date=date(2026, 10, 12),
        category=category,
        payer_id=payer_id,
        payment_type=PaymentType.DEBIT,
        split_strategy=EqualSplit(),
        currency=currency,
    )


def test_stored_balances_are_replaced_by_the_rows():
    share = _share(_expense(1000.0, payer_id=1), stored={"1": 999.0, "2": -999.0})
    SQLAlchemyExpenseRepository._derive_balances(share, MEMBERS)  # pylint: disable=protected-access
    assert share.balances == {"1": 500.0, "2": -500.0}


def test_usd_rows_are_converted_at_the_blue_rate():
    share = _share(_expense(100.0, payer_id=1, currency="USD"))
    with patch("template.service_layer.currency_service.get_blue_rate", return_value=1500.0):
        SQLAlchemyExpenseRepository._derive_balances(share, MEMBERS)  # pylint: disable=protected-access
    assert share.balances == {"1": 75000.0, "2": -75000.0}


def test_a_row_that_no_longer_validates_keeps_the_stored_balances_and_logs(caplog):
    bad = _expense(200.0, payer_id=1)
    bad.split_strategy = MagicMock()
    bad.split_strategy.calculate_shares.side_effect = ValueError("amounts must sum to 200.0, got 150.0")
    share = _share(bad, stored={"1": 10.0, "2": -10.0})

    with caplog.at_level("WARNING", logger="template.adapters.repositories"):
        SQLAlchemyExpenseRepository._derive_balances(share, MEMBERS)  # pylint: disable=protected-access

    assert share.balances == {"1": 10.0, "2": -10.0}
    assert any("2026-10" in r.getMessage() and "must sum" in r.getMessage() for r in caplog.records)
