from decimal import Decimal

import pytest

from template.domain.models.member import Member
from template.domain.models.split import EqualSplit, ExactAmountsSplit, PercentageSplit


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

    def test_equal_split_all_members_no_participant_ids(self, members):
        strategy = EqualSplit()
        shares = strategy.calculate_shares(300.0, members)
        assert shares[1] == 100.0
        assert shares[2] == 100.0
        assert shares[3] == 100.0

    def test_equal_split_subset_excludes_non_participant(self, members):
        strategy = EqualSplit(participant_ids=[1, 3])
        shares = strategy.calculate_shares(300.0, members)
        assert shares[1] == 150.0
        assert shares[2] == 0.0
        assert shares[3] == 150.0

    def test_equal_split_subset_rounding(self, members):
        strategy = EqualSplit(participant_ids=[1, 2, 3])
        shares = strategy.calculate_shares(1000.0, members)
        assert abs(sum(shares.values()) - 1000.0) < 0.02

    def test_equal_split_empty_participant_ids_raises(self):
        with pytest.raises(ValueError):
            EqualSplit(participant_ids=[])

    def test_equal_split_subset_ids_not_in_members_gives_zero(self, members):
        # participant_ids contains an ID that doesn't exist in passed members
        strategy = EqualSplit(participant_ids=[99])
        with pytest.raises(ValueError, match="No participants"):
            strategy.calculate_shares(100.0, members)

    def test_exact_amounts_split_basic(self, members):
        strategy = ExactAmountsSplit({1: 300.0, 2: 700.0})
        shares = strategy.calculate_shares(1000.0, members)
        assert shares[1] == 300.0
        assert shares[2] == 700.0
        assert shares[3] == 0.0

    def test_exact_amounts_split_sum_mismatch_raises(self, members):
        strategy = ExactAmountsSplit({1: 300.0, 2: 600.0})
        with pytest.raises(ValueError, match="must sum to"):
            strategy.calculate_shares(1000.0, members)

    def test_exact_amounts_split_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            ExactAmountsSplit({})

    def test_exact_amounts_split_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            ExactAmountsSplit({1: -10.0, 2: 110.0})

    def test_exact_amounts_split_zero_allowed(self, members):
        strategy = ExactAmountsSplit({1: 0.0, 2: 1000.0})
        shares = strategy.calculate_shares(1000.0, members)
        assert shares[1] == 0.0
        assert shares[2] == 1000.0

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
