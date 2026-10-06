"""USD expenses in group balances: split in dollars, then convert each part to ARS."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare, expense_shares_in_ars
from template.domain.models.split import EqualSplit, ExactAmountsSplit

RATE = 1500.0
RATE_PATH = "template.service_layer.currency_service.get_blue_rate"
MEMBERS = {
    1: Member(id=1, name="John", telephone="+1234567890", email="john@example.com"),
    2: Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"),
}


def _expense(amount, split, currency="USD", payment_type=PaymentType.DEBIT, installments=1, payer_id=1):
    category = Category()
    category.name = "viajes"
    return Expense(
        description="Hotel",
        amount=amount,
        date=date(2026, 10, 3),
        category=category,
        payer_id=payer_id,
        payment_type=payment_type,
        installments=installments,
        split_strategy=split,
        currency=currency,
    )


@pytest.fixture
def manager(mock_repository):
    group_repo = MagicMock()
    group_repo.list_members.return_value = list(MEMBERS.values())
    return ExpenseManager(mock_repository, group_id=1, group_repo=group_repo)


# --- the helper -------------------------------------------------------------------------


def test_helper_leaves_ars_untouched():
    paid, shares = expense_shares_in_ars(_expense(300.0, EqualSplit(), currency="ARS"), list(MEMBERS.values()), RATE)
    assert paid == 300.0
    assert shares == {1: 150.0, 2: 150.0}


def test_helper_splits_usd_exact_amounts_in_dollars_then_converts():
    """Regression: converting first made ExactAmountsSplit compare US$ parts to an ARS total."""
    expense = _expense(200.0, ExactAmountsSplit({1: 150.0, 2: 50.0}))
    paid, shares = expense_shares_in_ars(expense, list(MEMBERS.values()), RATE)
    assert paid == 300000.0
    assert shares == {1: 225000.0, 2: 75000.0}


def test_helper_shares_add_up_to_paid_after_rounding():
    expense = _expense(10.0, EqualSplit())  # US$5 each
    paid, shares = expense_shares_in_ars(expense, list(MEMBERS.values()), 1234.567)
    assert paid == 12345.67
    assert round(sum(shares.values()), 2) == paid


# --- balances -----------------------------------------------------------------------------


def test_usd_exact_split_balances_in_ars():
    share = MonthlyShare(2026, 10, 1)
    share.add_expense(_expense(200.0, ExactAmountsSplit({1: 150.0, 2: 50.0})), MEMBERS, usd_rate=RATE)
    assert share.balances == {"1": 75000.0, "2": -75000.0}


def test_create_usd_exact_split_expense(manager):
    with patch(RATE_PATH, return_value=RATE):
        manager.create_and_add_expense(_expense(200.0, ExactAmountsSplit({1: 150.0, 2: 50.0})))
    assert manager.get_monthly_balance(2026, 10).balances == {"1": 75000.0, "2": -75000.0}


def test_usd_credit_installments_keep_their_currency(manager):
    """Regression: each cuota was built without currency=, so US$300 in 3 became $100 rows."""
    with patch(RATE_PATH, return_value=RATE):
        manager.create_and_add_expense(_expense(300.0, EqualSplit(), payment_type=PaymentType.CREDIT, installments=3))
    for month in (11, 12):
        share = manager.get_monthly_balance(2026, month)
        assert share.expenses[0].currency == "USD"
        assert share.balances == {"1": 75000.0, "2": -75000.0}
    share = manager.get_monthly_balance(2027, 1)
    assert share.expenses[0].currency == "USD"


# --- settlement ---------------------------------------------------------------------------


def test_settle_recalculates_stale_raw_dollar_balances(manager):
    """Balances stored before the USD fix are raw dollars; settling must not transfer those."""
    with patch(RATE_PATH, return_value=RATE):
        manager.create_and_add_expense(_expense(200.0, EqualSplit()))
        stale = manager.get_monthly_balance(2026, 10)
        stale.balances = {"1": 100.0, "2": -100.0}  # what the old create path stored

        manager.settle_monthly_share(2026, 10)

    share = manager.get_monthly_balance(2026, 10)
    balancing = [e for e in share.expenses if e.category.name == "balance"]
    assert len(balancing) == 1
    assert balancing[0].amount == 150000.0
    assert balancing[0].payer_id == 2


def test_settle_refuses_usd_month_without_a_rate(manager):
    with patch(RATE_PATH, return_value=RATE):
        manager.create_and_add_expense(_expense(200.0, EqualSplit()))
    with patch(RATE_PATH, return_value=None):
        with pytest.raises(ValueError, match="cotización"):
            manager.settle_monthly_share(2026, 10)
    assert not manager.get_monthly_balance(2026, 10).is_settled


def test_settle_ars_month_needs_no_rate(manager):
    manager.create_and_add_expense(_expense(200.0, EqualSplit(), currency="ARS"))
    with patch(RATE_PATH, return_value=None):
        manager.settle_monthly_share(2026, 10)
    assert manager.get_monthly_balance(2026, 10).is_settled


def test_usd_exact_split_at_the_tolerance_still_nets_to_zero():
    """An exact split is accepted within US$0.01; at a high rate that cent is ~AR$15, which
    must still land on a part instead of leaving the month unbalanced."""
    expense = _expense(200.0, ExactAmountsSplit({1: 50.0, 2: 149.99}))
    paid, shares = expense_shares_in_ars(expense, list(MEMBERS.values()), 1437.5)
    assert paid == 287500.0
    assert round(sum(shares.values()), 2) == paid

    share = MonthlyShare(2026, 10, 1)
    share.add_expense(expense, MEMBERS, usd_rate=1437.5)
    assert round(sum(share.balances.values()), 2) == 0.0


def test_settle_with_a_member_who_left_does_not_crash(manager):
    """Settling recalculates; a balance key for someone no longer in the group must not
    raise KeyError (it used to, in the debug print)."""
    expense = _expense(300.0, EqualSplit(), currency="ARS", payer_id=3)  # 3 left the group
    manager.create_and_add_expense(expense)
    manager.settle_monthly_share(2026, 10)
    assert manager.get_monthly_balance(2026, 10).is_settled
