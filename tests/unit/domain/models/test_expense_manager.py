from datetime import date
from decimal import Decimal

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.member import Member
from template.domain.models.models import Expense, ExpenseManager
from template.domain.models.split import EqualSplit


class TestExpenseManager:
    @pytest.fixture
    def manager(self):
        manager = ExpenseManager()
        manager.add_member(Member(id=1, name="John", telephone="+1234567890"))
        manager.add_member(Member(id=2, name="Jane", telephone="+1234567891"))
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
            date=date(2024, 3, 15),
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
        new_member = Member(id=3, name="Bob", telephone="+1234567892")
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
        for month in range(4, 7):  # April, May, June
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
