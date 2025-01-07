"""
Pytest Fixtures.
"""
from datetime import date
from typing import Dict, List, Optional
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.repository import ExpenseRepository

# Mock database settings before importing app
with patch.dict("os.environ", {"DATABASE_URL": "postgresql://postgres:postgres@db:5432/expense_manager_test"}):
    from template.main import app


@pytest.fixture(name="test_client")
def fixture_test_client() -> TestClient:
    """
    Create a test client for the FastAPI application.

    Returns:
        TestClient: A test client for the app.
    """
    return TestClient(app)


@pytest.fixture  # noqa: F811
def mock_repository():  # noqa: F811, C901
    """Fixture that provides a mock expense repository for testing."""

    class MockExpenseRepository(ExpenseRepository):
        def __init__(self):
            self.expenses = []
            self.monthly_shares = {}
            self.session = None  # For member repository compatibility
            self.next_id = 1  # To simulate auto-incrementing IDs

        def add(self, expense: Expense, monthly_share_id: int) -> None:
            """Add an expense to the repository."""
            expense.id = self.next_id  # Assign an ID to the expense
            self.next_id += 1  # Increment the ID for the next expense
            self.expenses.append(expense)
            print(f"expense id: {expense.id}")

        def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
            self.monthly_shares[monthly_share.period_key] = monthly_share
            for expense in monthly_share.expenses:
                if not expense.id:  # New expense
                    self.add(expense, 1)

        def get_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
            key = f"{year}-{month:02d}"
            return self.monthly_shares.get(key)

        def get_all_monthly_shares(self) -> Dict[str, MonthlyShare]:
            return self.monthly_shares

        def update_expense(self, expense: Expense) -> None:
            """Update an existing expense in the repository."""
            print(f"updating the expense {expense.id}")
            for i, existing_expense in enumerate(self.expenses):
                if existing_expense.id == expense.id:
                    self.expenses[i] = expense
                    break

        def delete_expense(self, expense_to_delete: Expense) -> None:
            """Mock implementation to delete an expense."""
            print(f"deleting the expense {expense_to_delete.id}")
            self.expenses = [expense for expense in self.expenses if expense.id != expense_to_delete.id]

        def get_expense(self, expense_id: int) -> Expense:
            """Mock implementation to get an expense by ID."""
            for expense in self.expenses:
                if expense.id == expense_id:
                    return expense
            raise ValueError("Expense not found")

        def get_expenses_by_date(self, specific_date: date) -> List[Expense]:
            """Mock implementation to get expenses by date."""
            return [expense for expense in self.expenses if expense.date == specific_date]

        def settle_monthly_share(self, year: int, month: int) -> None:
            """Mock implementation to settle a monthly share."""
            print(f"Settling monthly share for {year}-{month:02d}")
            monthly_share = self.get_monthly_share(year, month)
            if monthly_share:
                monthly_share.settle()
                print("Monthly share settled successfully.")
            else:
                print("Monthly share not found.")

    return MockExpenseRepository()  # noqa: C901
