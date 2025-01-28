import copy
from datetime import date
from decimal import Decimal

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.split import EqualSplit


class TestExpenseManager:
    @pytest.fixture
    def manager(self, mock_repository):
        manager = ExpenseManager(mock_repository)
        manager.add_member(Member(id=1, name="John", telephone="+1234567890", email="john@example.com"))
        manager.add_member(Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"))
        return manager

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
    def credit_expense(self):
        category = Category()
        category.name = "food"
        return Expense(
            description="Test Credit",
            amount=300.0,
            date=date(2024, 2, 17),
            category=category,
            payer_id=1,
            payment_type=PaymentType.CREDIT,
            installments=3,
            split_strategy=EqualSplit(),
        )

    def test_add_member(self, manager):
        """
        GIVEN an ExpenseManager
        WHEN adding a new member
        THEN the member should be stored
        """
        new_member = Member(id=3, name="Bob", telephone="+1234567892", email="bob@example.com")
        manager.add_member(new_member)
        assert manager.members[3] == new_member

    def test_create_debit_expense(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager
        WHEN creating a debit expense
        THEN it should be added to the correct monthly share
        """
        manager.create_and_add_expense(debit_expense)

        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 1
        assert monthly_share.expenses[0].amount == Decimal("100")

    def test_create_credit_expense(self, manager, credit_expense):
        """
        GIVEN an ExpenseManager
        WHEN creating a credit expense with installments
        THEN it should create multiple monthly shares with installments
        """
        manager.create_and_add_expense(credit_expense)

        # Credit payments start next month
        for month in range(3, 6):  # March, April, May
            monthly_share = manager.get_monthly_balance(2024, month)
            assert monthly_share is not None
            assert len(monthly_share.expenses) == 1
            assert monthly_share.expenses[0].amount == Decimal("100")  # 300/3 installments

    def test_settle_monthly_share(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager with expenses
        WHEN settling a monthly share
        THEN it should be marked as settled
        """
        manager.create_and_add_expense(debit_expense)
        manager.settle_monthly_share(2024, 3)

        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None
        assert monthly_share.is_settled

    def test_create_multiple_expenses(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager
        WHEN creating multiple expenses
        THEN all expenses should be processed correctly
        """
        # Create first expense
        manager.create_and_add_expense(debit_expense)

        # Create second expense
        second_expense = copy.deepcopy(debit_expense)
        second_expense.description = "Second Test Debit"
        manager.create_and_add_expense(second_expense)

        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 2

    def test_update_expense_recalculates_balances(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager with existing expenses
        WHEN updating an expense
        THEN the balances should be recalculated correctly
        """
        # Create and add an initial expense

        manager.create_and_add_expense(debit_expense)

        expenses = manager.repository.get_expenses_by_date(debit_expense.date)
        assert len(manager.repository.expenses) == 1
        expense_id = expenses[0].id

        category = Category()
        category.name = "food"

        updated_expense = Expense(
            id=expense_id,
            description="Test Debit",
            amount=400.0,
            date=date(2024, 3, 15),
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )

        manager.update_expense(updated_expense)

        expenses = manager.repository.get_expenses_by_date(debit_expense.date)
        assert expenses[0].amount == 400

        # Check the monthly share balances
        monthly_share = manager.get_monthly_balance(2024, 3)
        print(monthly_share.expenses)
        assert monthly_share is not None
        assert monthly_share.balances[str(1)] == 200.0  # Payer should have a balance of 200
        assert monthly_share.balances[str(2)] == -200.0  # Other member should owe 200

    def test_delete_expense_recalculates_balances(self, manager, debit_expense, credit_expense):
        """
        GIVEN an ExpenseManager with existing expenses
        WHEN deleting an expense
        THEN the balances should be recalculated correctly
        """
        # Create and add an initial expense
        manager.create_and_add_expense(debit_expense)
        manager.create_and_add_expense(credit_expense)

        # Fetch the monthly share before deletion
        monthly_share = manager.get_monthly_balance(debit_expense.date.year, debit_expense.date.month)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 2  # Ensure the expense is added
        print(monthly_share.balances)
        # Delete the expense
        manager.delete_expense(debit_expense)

        # Check that the expense has been removed
        monthly_share = manager.get_monthly_balance(debit_expense.date.year, debit_expense.date.month)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 1  # Ensure the expense is deleted

        # Recalculate balances for the monthly share
        monthly_share.recalculate_balances(manager.members)

        print(monthly_share.balances)
        # Check the balances after deletion
        assert monthly_share.balances[str(1)] == 50.0  # Payer should have a balance of 0
        assert monthly_share.balances[str(2)] == -50.0  # Other member should also have a balance of 0

    def test_delete_expense__leaving_empty_balance(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager with existing expenses
        WHEN deleting an expense
        THEN the balances should be recalculated correctly
        """
        # Create and add an initial expense
        manager.create_and_add_expense(debit_expense)

        # Fetch the monthly share before deletion
        monthly_share = manager.get_monthly_balance(debit_expense.date.year, debit_expense.date.month)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 1  # Ensure the expense is added
        print(monthly_share.balances)
        # Delete the expense
        manager.delete_expense(debit_expense)

        # Check that the expense has been removed
        monthly_share = manager.get_monthly_balance(debit_expense.date.year, debit_expense.date.month)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 0  # Ensure the expense is deleted

        # Recalculate balances for the monthly share
        monthly_share.recalculate_balances(manager.members)

        print(monthly_share.balances)
        # Check the balances after deletion
        assert monthly_share.balances == {}

    def test_settle_monthly_share_updates_balances(self, manager, debit_expense):
        """
        GIVEN an ExpenseManager with an expense
        WHEN settling a monthly share
        THEN it should update balances correctly
        """
        # Add an expense to the monthly share
        manager.create_and_add_expense(debit_expense)

        monthly_share = manager.get_monthly_balance(2024, 3)
        print(monthly_share.balances)

        # Settle the monthly share
        manager.settle_monthly_share(2024, 3)

        # Fetch the monthly share to check balances
        monthly_share = manager.get_monthly_balance(2024, 3)
        print(monthly_share.balances)
        assert monthly_share is not None
        assert monthly_share.is_settled

        # Check balances after settling
        assert monthly_share.balances[str(1)] == 0.0  # Payer should have a balance of 0
        assert monthly_share.balances[str(2)] == 0.0  # Other member should owe 100

    def test_settle_monthly_share_creates_balancing_expense(self, manager):
        """
        GIVEN an ExpenseManager with expenses
        WHEN settling a monthly share with balances
        THEN it should create a balancing expense
        """
        category = Category()
        category.name = "food"
        # Create and add expenses
        expense1 = Expense(
            description="Expense 1",
            amount=200,
            date="2024-03-15",
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )
        expense2 = Expense(
            description="Expense 2",
            amount=100,
            date="2024-03-15",
            category=category,
            payer_id=2,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )
        manager.create_and_add_expense(expense1)
        manager.create_and_add_expense(expense2)

        # Settle the monthly share
        manager.settle_monthly_share(2024, 3)

        # Check if the balancing expense was created
        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 3  # Two original expenses + one balancing expense

        # Check the balancing expense
        balancing_expense = monthly_share.expenses[-1]  # The last expense should be the balancing one
        assert balancing_expense.description == "Balancing Expense"
        assert balancing_expense.amount == 50.0  # Should match the balance
        assert balancing_expense.payer_id == 2  # The one who owes should be the payer
