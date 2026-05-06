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

    def test_add_member(self, manager: ExpenseManager):
        """
        GIVEN an ExpenseManager
        WHEN adding a new member
        THEN the member should be stored
        """
        new_member = Member(id=3, name="Bob", telephone="+1234567892", email="bob@example.com")
        manager.add_member(new_member)
        assert manager.members[3] == new_member

    def test_create_debit_expense(self, manager: ExpenseManager, debit_expense: Expense):
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

    def test_create_credit_expense(self, manager: ExpenseManager, credit_expense: Expense):
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

    def test_settle_monthly_share(self, manager: ExpenseManager, debit_expense: Expense):
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

    def test_create_multiple_expenses(self, manager: ExpenseManager, debit_expense: Expense):
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

    def test_update_expense_recalculates_balances(self, manager: ExpenseManager, debit_expense: Expense):
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

    def test_delete_expense_recalculates_balances(
        self, manager: ExpenseManager, debit_expense: Expense, credit_expense: Expense
    ):
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
        manager.delete_expense(debit_expense.id)

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

    def test_delete_expense__leaving_empty_balance(self, manager: ExpenseManager, debit_expense: Expense):
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
        manager.delete_expense(debit_expense.id)

        # Check that the expense has been removed
        monthly_share = manager.get_monthly_balance(debit_expense.date.year, debit_expense.date.month)
        assert monthly_share is not None
        assert len(monthly_share.expenses) == 0  # Ensure the expense is deleted

        # Recalculate balances for the monthly share
        monthly_share.recalculate_balances(manager.members)

        print(monthly_share.balances)
        # Check the balances after deletion
        assert monthly_share.balances == {}

    def test_settle_monthly_share_updates_balances(self, manager: ExpenseManager, debit_expense: Expense):
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

    def test_settle_monthly_share_creates_balancing_expense(self, manager: ExpenseManager):
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

    def test_settle_monthly_share_with_three_members_creates_one_balancing_expense_per_debtor(
        self, manager: ExpenseManager
    ):
        """
        GIVEN an ExpenseManager with three members where one paid for everyone
        WHEN settling the monthly share
        THEN one balancing expense per debtor should be created, all owed to the single creditor
        """
        manager.add_member(Member(id=3, name="Bob", telephone="+1234567892", email="bob@example.com"))

        category = Category()
        category.name = "food"
        expense = Expense(
            description="Dinner for three",
            amount=300,
            date="2024-03-15",
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )
        manager.create_and_add_expense(expense)

        # Pre-settle balance: 1=+200, 2=-100, 3=-100
        manager.settle_monthly_share(2024, 3)

        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None
        assert monthly_share.is_settled

        balancing_expenses = [e for e in monthly_share.expenses if e.description == "Balancing Expense"]
        assert len(balancing_expenses) == 2

        # Each debtor should appear exactly once as payer of a balancing expense; creditor is member 1
        payer_ids = sorted(e.payer_id for e in balancing_expenses)
        assert payer_ids == [2, 3]
        assert all(e.amount == 100.0 for e in balancing_expenses)
        # All balancing expenses settle to member 1
        for expense in balancing_expenses:
            percentages = expense.split_strategy.percentages
            assert percentages[1] == 100.0
            assert percentages[expense.payer_id] == 0.0

        # Total transferred equals the creditor's positive balance
        assert sum(e.amount for e in balancing_expenses) == 200.0

    def test_settle_monthly_share_with_multiple_creditors_and_debtors(self, manager: ExpenseManager):
        """
        GIVEN an ExpenseManager with two creditors and two debtors of equal magnitude
        WHEN settling the monthly share
        THEN one balancing expense per matched pair should be created
        """
        manager.add_member(Member(id=3, name="Bob", telephone="+1234567892", email="bob@example.com"))
        manager.add_member(Member(id=4, name="Alice", telephone="+1234567893", email="alice@example.com"))

        category = Category()
        category.name = "food"
        expense1 = Expense(
            description="Lunch",
            amount=100,
            date="2024-03-15",
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )
        expense2 = Expense(
            description="Coffee",
            amount=100,
            date="2024-03-15",
            category=category,
            payer_id=3,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )
        manager.create_and_add_expense(expense1)
        manager.create_and_add_expense(expense2)

        # Pre-settle: 1=+50, 2=-50, 3=+50, 4=-50
        manager.settle_monthly_share(2024, 3)

        monthly_share = manager.get_monthly_balance(2024, 3)
        assert monthly_share is not None

        balancing_expenses = [e for e in monthly_share.expenses if e.description == "Balancing Expense"]
        assert len(balancing_expenses) == 2

        # Total balancing amount equals total positive balance
        assert sum(e.amount for e in balancing_expenses) == 100.0

        # Each balancing expense pairs one debtor with one creditor (no self-pairing)
        for be in balancing_expenses:
            percentages = be.split_strategy.percentages
            recipient_ids = [mid for mid, pct in percentages.items() if pct == 100.0]
            assert len(recipient_ids) == 1
            assert recipient_ids[0] != be.payer_id
