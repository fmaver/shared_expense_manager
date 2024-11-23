"""Module for managing expense splits between users."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict

from .models import Member


class SplitStrategy(ABC):
    @abstractmethod
    def calculate_shares(self, amount: Decimal, members: list["Member"]) -> Dict[int, Decimal]:
        """Calculate how much each member should pay"""


class EqualSplit(SplitStrategy):
    def calculate_shares(self, amount: Decimal, members: list["Member"]) -> Dict[int, Decimal]:
        share = amount / len(members)
        return {member.id: share for member in members}


class PercentageSplit(SplitStrategy):
    def __init__(self, percentages: Dict[int, Decimal]):
        """Initialize a percentage-based split strategy.

        Args:
            percentages: Dictionary mapping member IDs to their percentage shares
        """
        self.validate_percentages(percentages)
        self.percentages = percentages

    def calculate_shares(self, amount: Decimal, members: list["Member"]) -> Dict[int, Decimal]:
        """Calculate shares based on predefined percentages.

        Args:
            amount: Total amount to split
            members: List of members involved in the split

        Returns:
            Dictionary mapping member IDs to their monetary shares
        """
        return {member_id: (amount * percentage / 100) for member_id, percentage in self.percentages.items()}

    @staticmethod
    def validate_percentages(percentages: Dict[int, Decimal]) -> None:
        """Validate that the provided percentages sum to 100.

        Args:
            percentages: Dictionary mapping member IDs to their percentage shares

        Raises:
            ValueError: If the percentages don't sum to 100
        """
        total = sum(percentages.values())
        if total != 100:
            raise ValueError(f"Percentages must sum to 100, got {total}")
