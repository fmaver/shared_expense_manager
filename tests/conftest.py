"""
Pytest Fixtures.
"""
from typing import Dict, Optional

import pytest
from starlette.testclient import TestClient

from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.repository import ExpenseRepository
from template.main import app


@pytest.fixture(name="test_client")
def fixture_test_client() -> TestClient:
    """
    Create a test client for the FastAPI application.

    Returns:
        TestClient: A test client for the app.
    """
    return TestClient(app)


@pytest.fixture
def mock_repository():
    """Fixture that provides a mock expense repository for testing.

    Returns:
        MockExpenseRepository: A mock implementation of the ExpenseRepository.
    """

    class MockExpenseRepository(ExpenseRepository):
        def __init__(self):
            self.expenses = []
            self.monthly_shares = {}
            self.session = None  # For member repository compatibility

        def add(self, expense: Expense, monthly_share_id: int) -> None:
            """Add an expense to the repository.

            Args:
                expense: The expense to add
                monthly_share_id: The ID of the monthly share for the expense
            """
            self.expenses.append(expense)

        def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
            self.monthly_shares[monthly_share.period_key] = monthly_share

        def get_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
            key = f"{year}-{month:02d}"
            return self.monthly_shares.get(key)

        def get_all_monthly_shares(self) -> Dict[str, MonthlyShare]:
            return self.monthly_shares

    return MockExpenseRepository()
