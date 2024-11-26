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

    def calculate_shares(self, amount: float, members: list[Member]) -> Dict[int, float]:
        """Calculate shares based on predefined percentages."""
        # Ensure all members have a percentage, default to 0
        shares = {member.id: 0.0 for member in members}

        # Apply defined percentages
        for member_id, percentage in self.percentages.items():
            if member_id in shares:
                shares[member_id] = round((amount * percentage / 100), 2)
        return shares

    @staticmethod
    def validate_percentages(percentages: Dict[int, float]) -> None:
        """Validate that the provided percentages sum to 100."""
        total = sum(percentages.values())
        if abs(total - 100) > 0.01:  # Using small epsilon for float comparison
            raise ValueError(f"Percentages must sum to 100, got {total}")
