"""Pytest Fixtures.

Sets DATABASE_URL before any template import so database.py picks up the right engine.
"""

import os
from datetime import date
from typing import Dict, List, Optional

import pytest
from starlette.testclient import TestClient

# Must be set before template.adapters.database is imported (create_engine runs at module level)
os.environ.setdefault("DATABASE_ENV", "PROD")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/test_expense_manager",
    ),
)

# pylint: disable=wrong-import-position
from template.adapters.repositories import _strip_installment_suffix  # noqa: E402
from template.domain.models.enums import PaymentType  # noqa: E402
from template.domain.models.models import Expense, MonthlyShare  # noqa: E402
from template.domain.models.repository import ExpenseRepository  # noqa: E402


@pytest.fixture
def whatsapp_on(monkeypatch):
    """Turn the WhatsApp kill switch on for one test (it is off when WHATSAPP_ENABLED is unset)."""
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")


@pytest.fixture(name="test_client")
def fixture_test_client() -> TestClient:
    """Test client without lifespan — safe to use without a live DB."""
    from template.main import app  # pylint: disable=import-outside-toplevel

    return TestClient(app)


def _purchase_total(expense: Expense) -> float:
    return expense.amount * expense.installments if expense.payment_type == PaymentType.CREDIT else expense.amount


def _fake_find_similar_expenses(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
    monthly_shares, group_id: int, year: int, month: int, amount: float, description: str, expense_date, currency: str
) -> List[Expense]:
    """In-memory mirror of SQLAlchemyExpenseRepository.find_similar_expenses — see its docstring."""
    tolerance = 0.005
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    normalized = _strip_installment_suffix(description).strip().lower()

    matches: Dict[int, Expense] = {}
    for ms in monthly_shares:
        if ms.group_id != group_id:
            continue
        in_description_scope = (ms.year, ms.month) in {(year, month), (next_year, next_month)}
        for e in ms.expenses:
            if e.installment_no != 1 or e.currency != currency:
                continue
            total = _purchase_total(e)
            same_total = abs(total - amount) < tolerance
            if e.date == expense_date and same_total:
                matches[e.id] = e
                continue
            same_description = _strip_installment_suffix(e.description).strip().lower() == normalized
            if in_description_scope and same_description and same_total:
                matches[e.id] = e
    return list(matches.values())


@pytest.fixture
def mock_repository():  # noqa: C901
    """In-memory expense repository for unit tests."""

    class MockExpenseRepository(ExpenseRepository):
        def __init__(self):
            self.expenses = []
            self.monthly_shares = {}
            self.session = None
            self.next_id = 1

        def add(self, expense: Expense, monthly_share_id: int, group_id: int) -> None:
            expense.id = self.next_id
            self.next_id += 1
            self.expenses.append(expense)

        def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
            self.monthly_shares[monthly_share.period_key] = monthly_share
            for expense in monthly_share.expenses:
                if not expense.id:
                    self.add(expense, 1, monthly_share.group_id)

        def get_monthly_share(self, year: int, month: int, group_id: int) -> Optional[MonthlyShare]:
            key = f"{year}-{month:02d}"
            return self.monthly_shares.get(key)

        def get_all_monthly_shares(self, group_id: int) -> Dict[str, MonthlyShare]:
            return self.monthly_shares

        def update_expense(self, expense: Expense) -> None:
            for i, existing in enumerate(self.expenses):
                if existing.id == expense.id:
                    self.expenses[i] = expense
                    break
            # Keep monthly_share expense lists in sync (real repo re-queries DB on get)
            for ms in self.monthly_shares.values():
                for i, e in enumerate(ms.expenses):
                    if e.id == expense.id:
                        ms.expenses[i] = expense
                        break

        def delete_expense(self, expense_id: int) -> None:
            # Cascade delete children (mirrors DB FK on parent_expense_id)
            child_ids = [e.id for e in self.expenses if e.parent_expense_id == expense_id]
            for child_id in child_ids:
                self.delete_expense(child_id)
            self.expenses = [e for e in self.expenses if e.id != expense_id]
            for ms in self.monthly_shares.values():
                ms.expenses = [e for e in ms.expenses if e.id != expense_id]

        def get_expense(self, expense_id: int) -> Optional[Expense]:
            return next((e for e in self.expenses if e.id == expense_id), None)

        def get_child_expenses(self, parent_expense_id: int) -> List[Expense]:
            return [e for e in self.expenses if e.parent_expense_id == parent_expense_id]

        def find_similar_expenses(  # pylint: disable=too-many-arguments, too-many-positional-arguments
            self,
            group_id: int,
            year: int,
            month: int,
            amount: float,
            description: str,
            expense_date: date,
            currency: str = "ARS",
        ) -> List[Expense]:
            """Mirrors SQLAlchemyExpenseRepository.find_similar_expenses — see its docstring."""
            return _fake_find_similar_expenses(
                self.monthly_shares.values(), group_id, year, month, amount, description, expense_date, currency
            )

        def get_expenses_by_date(self, specific_date: date) -> List[Expense]:
            return [e for e in self.expenses if e.date == specific_date]

        def settle_monthly_share(self, year: int, month: int, group_id: int) -> None:
            ms = self.get_monthly_share(year, month, group_id)
            if ms:
                ms.settle()

        def reassign_expense_to_monthly_share(self, expense_id: int, year: int, month: int, group_id: int) -> None:
            # Mirrors the real repo: moving the share FK takes the row out of whatever
            # share held it. The caller owns the in-memory list of the target share, so
            # nothing is appended here. A pure no-op would hide a caller that forgets to
            # reassign at all, which is a bug this fixture is meant to expose.
            if self.get_expense(expense_id) is None:
                return
            for ms in self.monthly_shares.values():
                ms.expenses = [e for e in ms.expenses if e.id != expense_id]
            key = f"{year}-{month:02d}"
            if key not in self.monthly_shares:
                self.monthly_shares[key] = MonthlyShare(year, month, group_id)

    return MockExpenseRepository()
