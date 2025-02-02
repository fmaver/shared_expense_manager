from decimal import Decimal

import pytest

from template.domain.models.member import Member
from template.domain.models.split import EqualSplit, PercentageSplit


class TestSplitStrategies:
    @pytest.fixture
    def members(self):
        return [
            Member(id=1, name="John", telephone="+1234567890", email="john@example.com"),
            Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"),
            Member(id=3, name="Bob", telephone="+1234567892", email="bob@example.com"),
        ]

    def test_equal_split(self, members):
        """
        GIVEN an amount and list of members
        WHEN using EqualSplit strategy
        THEN it should split the amount equally
        """
        amount = 300.0
        strategy = EqualSplit()
        shares = strategy.calculate_shares(amount, members)

        expected_share = 100.0
        assert all(share == expected_share for share in shares.values())
        assert len(shares) == len(members)

    def test_percentage_split_valid(self, members):
        """
        GIVEN valid percentages that sum to 100
        WHEN using PercentageSplit strategy
        THEN it should split according to percentages
        """
        percentages = {1: 50.0, 2: 30.0, 3: 20.0}
        amount = 100.0
        strategy = PercentageSplit(percentages)
        shares = strategy.calculate_shares(amount, members)

        assert shares[1] == 50.0
        assert shares[2] == 30.0
        assert shares[3] == 20.0

    def test_percentage_split_invalid(self):
        """
        GIVEN percentages that don't sum to 100
        WHEN creating PercentageSplit strategy
        THEN it should raise ValueError
        """
        with pytest.raises(ValueError):
            PercentageSplit({1: Decimal("50"), 2: Decimal("20")})

    def test_percentage_split_with_members(self, members):
        """
        GIVEN a percentage split with specific members
        WHEN calculating shares
        THEN it should calculate correct amounts for each member
        """
        # Set percentages for members 1 and 2
        percentages = {1: 60.0, 2: 40.0}
        amount = 100.0
        strategy = PercentageSplit(percentages)

        # Calculate shares
        shares = strategy.calculate_shares(amount, members)

        # Verify shares
        assert shares[1] == 60.0  # Member 1 should pay 60%
        assert shares[2] == 40.0  # Member 2 should pay 40%
        assert shares[3] == 0.0  # Member 3 should pay nothing
