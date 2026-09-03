"""Regression tests for editing a multi-installment credit expense.

Editing such an expense used to scramble it, because `update_credit_expense`:

  1. never reassigned any row to its new monthly share, so changing the date left
     every installment sitting in its original month; and
  2. stamped `installment_no` from the position of a row in `get_child_expenses()`,
     which has no ORDER BY — so numbers landed on whichever child Postgres happened
     to return in that slot.

The two compound into a random permutation of cuota numbers over unchanged months,
which is why some months looked right and others did not.

Note on dates: every installment row deliberately stores the *purchase* date. The
month an installment falls in comes from its monthly share, not from `date`.
"""

from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit

PURCHASE_DATE = date(2026, 3, 22)
TOTAL = 43500.0
INSTALLMENTS = 9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager(mock_repository):
    from unittest.mock import MagicMock

    group_repo = MagicMock()
    group_repo.list_members.return_value = [
        Member(id=1, name="Fran", telephone="+5411111111", email="fran@example.com"),
    ]
    return ExpenseManager(mock_repository, group_id=1, group_repo=group_repo)


def _category(name: str = "entretenimiento") -> Category:
    category = Category()
    category.name = name
    return category


def _make_credit(manager: ExpenseManager, purchase_date: date = PURCHASE_DATE) -> Expense:
    """Create a 9-installment credit expense and return its parent row."""
    return manager.create_and_add_expense(
        Expense(
            description="Libro alas de sangre",
            amount=TOTAL,
            date=purchase_date,
            category=_category(),
            payer_id=1,
            payment_type=PaymentType.CREDIT,
            installments=INSTALLMENTS,
            split_strategy=EqualSplit(),
        )
    )


def _edited(parent: Expense, new_date: date, installments: int = INSTALLMENTS, total: float = TOTAL) -> Expense:
    """Build the Expense that the service layer hands to update_credit_expense."""
    return Expense(
        id=parent.id,
        description="Libro alas de sangre",
        amount=total,
        date=new_date,
        category=_category(),
        payer_id=1,
        payment_type=PaymentType.CREDIT,
        installments=installments,
        installment_no=1,
        split_strategy=EqualSplit(),
        parent_expense_id=parent.parent_expense_id,
    )


def _installment_by_month(manager: ExpenseManager, purchase_date: date, count: int) -> dict[str, int]:
    """Map 'YYYY-MM' → installment_no for each share an installment should live in."""
    found = {}
    for offset in range(1, count + 1):
        share_date = purchase_date + relativedelta(months=offset)
        share = manager.get_monthly_balance(share_date.year, share_date.month)
        key = f"{share_date.year}-{share_date.month:02d}"
        rows = [e for e in (share.expenses if share else []) if e.description.startswith("Libro alas de sangre")]
        assert len(rows) == 1, f"expected exactly one installment in {key}, found {len(rows)}"
        found[key] = rows[0].installment_no
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_creation_places_one_installment_per_month_in_order(manager):
    """Baseline: creation is correct — cuota k lands in purchase month + k."""
    parent = _make_credit(manager)
    assert parent.installment_no == 1

    by_month = _installment_by_month(manager, PURCHASE_DATE, INSTALLMENTS)
    assert list(by_month.values()) == list(range(1, INSTALLMENTS + 1))


def test_date_shift_moves_every_installment_forward_one_month(manager):
    """Shifting the purchase date one month must move all 9 rows one month forward.

    The reported symptom: cuota 1 stayed in its old month because no row was ever
    reassigned to a new monthly share.
    """
    parent = _make_credit(manager)
    new_date = PURCHASE_DATE + relativedelta(months=1)

    manager.update_credit_expense(_edited(parent, new_date))

    # Every installment sits in the right new month, numbered 1..9 in order.
    by_month = _installment_by_month(manager, new_date, INSTALLMENTS)
    assert list(by_month.values()) == list(range(1, INSTALLMENTS + 1))

    # And the month cuota 1 vacated no longer holds the expense.
    old_first = PURCHASE_DATE + relativedelta(months=1)
    old_share = manager.get_monthly_balance(old_first.year, old_first.month)
    stale = [e for e in (old_share.expenses if old_share else []) if e.installment_no == 1]
    assert stale == [], "cuota 1 was left behind in its original month"


def test_installment_numbers_survive_children_returned_in_any_order(manager, mock_repository):
    """installment_no must not depend on the order get_child_expenses() returns rows in.

    The real repository issues `filter_by(...).all()` with no ORDER BY, so Postgres
    may return children in any order. Reversing the order here stands in for that.
    """
    parent = _make_credit(manager)
    original = mock_repository.get_child_expenses
    mock_repository.get_child_expenses = lambda parent_id: list(reversed(original(parent_id)))

    manager.update_credit_expense(_edited(parent, PURCHASE_DATE))

    by_month = _installment_by_month(manager, PURCHASE_DATE, INSTALLMENTS)
    assert list(by_month.values()) == list(range(1, INSTALLMENTS + 1))


def test_descriptions_match_their_installment_number(manager):
    """The '(k/N)' suffix must agree with the row's installment_no after an edit."""
    parent = _make_credit(manager)
    new_date = PURCHASE_DATE + relativedelta(months=1)

    manager.update_credit_expense(_edited(parent, new_date))

    for offset in range(1, INSTALLMENTS + 1):
        share_date = new_date + relativedelta(months=offset)
        share = manager.get_monthly_balance(share_date.year, share_date.month)
        row = [e for e in share.expenses if e.description.startswith("Libro alas de sangre")][0]
        assert row.description.endswith(f"({row.installment_no}/{INSTALLMENTS})")
        assert row.installment_no == offset


def test_each_row_holds_total_divided_by_installments(manager):
    """Each row stores the per-installment amount, recomputed when N changes."""
    parent = _make_credit(manager)

    manager.update_credit_expense(_edited(parent, PURCHASE_DATE, installments=6, total=TOTAL))

    for offset in range(1, 7):
        share_date = PURCHASE_DATE + relativedelta(months=offset)
        share = manager.get_monthly_balance(share_date.year, share_date.month)
        row = [e for e in share.expenses if e.description.startswith("Libro alas de sangre")][0]
        assert row.amount == pytest.approx(TOTAL / 6)
        assert row.installments == 6


def test_reducing_installments_drops_the_last_cuotas(manager):
    """Going 9 → 4 must leave cuotas 1..4, not an arbitrary subset.

    The delete branch indexed the same unordered child list, so it removed whichever
    rows happened to sit at those positions.
    """
    parent = _make_credit(manager)

    manager.update_credit_expense(_edited(parent, PURCHASE_DATE, installments=4))

    by_month = _installment_by_month(manager, PURCHASE_DATE, 4)
    assert list(by_month.values()) == [1, 2, 3, 4]

    # Months 5..9 must be empty of this expense.
    for offset in range(5, INSTALLMENTS + 1):
        share_date = PURCHASE_DATE + relativedelta(months=offset)
        share = manager.get_monthly_balance(share_date.year, share_date.month)
        leftovers = [e for e in (share.expenses if share else []) if e.description.startswith("Libro alas de sangre")]
        assert leftovers == [], f"cuota left behind {offset} months out"


def test_installment_rows_keep_the_purchase_date(manager):
    """All rows store the purchase date; the month comes from the monthly share."""
    parent = _make_credit(manager)
    new_date = PURCHASE_DATE + relativedelta(months=1)

    manager.update_credit_expense(_edited(parent, new_date))

    for offset in range(1, INSTALLMENTS + 1):
        share_date = new_date + relativedelta(months=offset)
        share = manager.get_monthly_balance(share_date.year, share_date.month)
        row = [e for e in share.expenses if e.description.startswith("Libro alas de sangre")][0]
        assert row.date == new_date
