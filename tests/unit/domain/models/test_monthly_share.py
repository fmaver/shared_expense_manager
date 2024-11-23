from decimal import Decimal

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.split import EqualSplit


class TestMonthlyShare:
    @pytest.fixture
    def members(self):
        return {
            1: Member(id=1, name="John", telephone="+1234567890"),
            2: Member(id=2, name="Jane", telephone="+1234567891"),
        }

    @pytest.fixture
    def expense(self):
        category = Category()
        category.name = "food"
        return Expense(
            description="Test Expense",
            amount=Decimal("100"),
            date="2024-03-15",
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )

    def test_create_monthly_share(self):
        """
        GIVEN a year and month
        WHEN creating a MonthlyShare
        THEN it should initialize correctly
        """
        share = MonthlyShare(2024, 3)
        assert share.year == 2024
        assert share.month == 3
        assert not share.is_settled
        assert share.period_key == "2024-03"

    def test_settle_monthly_share(self):
        """
        GIVEN a MonthlyShare
        WHEN settling it
        THEN it should be marked as settled
        """
        share = MonthlyShare(2024, 3)
        share.settle()
        assert share.is_settled

    def test_cannot_add_expense_to_settled_share(self, expense, members):
        """
        GIVEN a settled MonthlyShare
        WHEN trying to add an expense
        THEN it should raise ValueError
        """
        share = MonthlyShare(2024, 3)
        share.settle()

        with pytest.raises(ValueError):
            share.add_expense(expense, members)

    def test_add_expense_updates_balances(self, expense, members):
        """
        GIVEN a MonthlyShare and an expense
        WHEN adding the expense
        THEN balances should be updated correctly
        """
        share = MonthlyShare(2024, 3)
        share.add_expense(expense, members)

        # For equal split of 100, each member should owe 50
        # Payer (id=1) paid 100 but owes 50, so balance is +50
        # Other member (id=2) owes 50
        assert share.balances[1] == Decimal("50")
        assert share.balances[2] == Decimal("-50")
