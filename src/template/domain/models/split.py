"""Module for managing expense splits between users."""

from abc import ABC, abstractmethod
from typing import Dict

from .member import Member


class SplitStrategy(ABC):
    @abstractmethod
    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Calculate how much each member should pay"""


class EqualSplit(SplitStrategy):
    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Calculate equal shares for all members."""
        share = round(amount / len(members), 2)  # Round to 2 decimal places
        return {member.id: share for member in members}


class PercentageSplit(SplitStrategy):
    def __init__(self, percentages: Dict[int, float]):
        """Initialize a percentage-based split strategy.

        Args:
            percentages: Dictionary mapping member IDs to their percentage shares
        """
        self.validate_percentages(percentages)
        self.percentages = percentages

    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Calculate shares based on predefined percentages."""
        print(f"A percentage split with {self.percentages}")
        # Initialize shares for all members to 0
        shares = {member.id: 0.0 for member in members}
        print(f"Shares: {shares}")
        total_allocated = 0.0
        # Calculate each member's share and track total allocated
        for member_id, percentage in self.percentages.items():
            if member_id in shares:
                print(f"member_id {member_id} in shares")
                share = round((amount * percentage / 100), 2)
                shares[member_id] = share
                total_allocated += share
        print(f"Shares: {shares}")

        # Handle any rounding discrepancy
        discrepancy = round(amount - total_allocated, 2)
        if discrepancy != 0:
            # Add the discrepancy to the member with the highest percentage
            max_percentage_member = max(self.percentages.items(), key=lambda x: x[1])[0]
            if max_percentage_member in shares:
                shares[max_percentage_member] = round(shares[max_percentage_member] + discrepancy, 2)
        print(f"Shares after rounding: {shares}")

        return shares

    @staticmethod
    def validate_percentages(percentages: Dict[int, float]) -> None:
        """Validate that the provided percentages sum to 100."""
        total = sum(percentages.values())
        if abs(total - 100) > 0.01:  # Using small epsilon for float comparison
            raise ValueError(f"Percentages must sum to 100, got {total}")
