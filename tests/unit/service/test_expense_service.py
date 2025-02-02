import copy
from datetime import date
from decimal import Decimal

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_service import ExpenseService


class TestExpenseService:
    @pytest.fixture
    def service(self, mock_repository):
        return ExpenseService(mock_repository)

    @pytest.fixture
    def debit_expense(self):
        category = Category()
        category.name = "food"
        return Expense(
            description="Test Debit",
            amount=100.0,
            date=date(2024, 3, 15),
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )

    @pytest.fixture
    def expense_data(self):
        return ExpenseCreate(
            description="Test Debit",
            amount=100.0,
            date=date(2024, 3, 15),
            category=CategorySchema(name="food"),
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal"),
        )

    def test_update_expense(self, service: ExpenseService, debit_expense, expense_data: ExpenseCreate):
        service._manager.add_member(Member(id=1, name="John", telephone="+1234567890", email="john@example.com"))
        service._manager.add_member(Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"))

        service.create_expense(expense_data)

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(expenses) == 1
        expense_id = expenses[0].id

        # Prepare updated expense data
        updated_expense_data = ExpenseCreate(
            description="Updated Test Debit",
            amount=150.0,
            date=date(2024, 3, 15),
            category=CategorySchema(name="food"),
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal"),
        )

        # Update the expense
        updated_expense = service.update_expense(expense_id, updated_expense_data)

        # Verify the expense has been updated
        assert updated_expense.description == "Updated Test Debit"
        assert updated_expense.amount == 150.0

    def test_delete_expense(self, service: ExpenseService, debit_expense, expense_data):
        service._manager.add_member(Member(id=1, name="John", telephone="+1234567890", email="john@example.com"))
        service._manager.add_member(Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"))

        # Create the expense
        service.create_expense(expense_data)

        # Check if the expense is saved in the mock repository
        assert len(service._manager.repository.expenses) == 1  # Check if one expense is saved
        assert service._manager.repository.expenses[0].description == expense_data.description  # Check the description
        assert service._manager.repository.expenses[0].amount == expense_data.amount  # Check the amount

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(service._manager.repository.expenses) == 1
        expense_id = expenses[0].id
        # Delete the expense
        service.delete_expense(expense_id)

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(service._manager.repository.expenses) == 0

        # Verify the expense is deleted
        with pytest.raises(ValueError):
            service.get_expense(expense_id)
