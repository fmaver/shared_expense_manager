"""Module for managing expense splits between users."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .member import Member


class SplitStrategy(ABC):
    @abstractmethod
    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Calculate how much each member should pay"""


class EqualSplit(SplitStrategy):
    def __init__(self, participant_ids: Optional[List[int]] = None):
        if participant_ids is not None and len(participant_ids) == 0:
            raise ValueError("participant_ids must be non-empty when provided")
        self.participant_ids = participant_ids

    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Calculate equal shares, optionally restricted to a subset of members."""
        if self.participant_ids is not None:
            participants = [m for m in members if m.id in self.participant_ids]
        else:
            participants = list(members)

        if not participants:
            raise ValueError("No participants available for equal split")

        share = round(amount / len(participants), 2)
        shares = {m.id: 0.0 for m in members}
        for m in participants:
            shares[m.id] = share

        # Assign rounding discrepancy to first participant
        total_assigned = round(share * len(participants), 2)
        discrepancy = round(amount - total_assigned, 2)
        if discrepancy != 0:
            shares[participants[0].id] = round(shares[participants[0].id] + discrepancy, 2)

        return shares


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
        # Initialize shares for all members to 0
        shares = {member.id: 0.0 for member in members}
        total_allocated = 0.0
        # Calculate each member's share and track total allocated
        for member_id, percentage in self.percentages.items():
            member_id = int(member_id)
            if member_id in shares:
                share = round((amount * percentage / 100), 2)
                shares[member_id] = share
                total_allocated += share

        # Handle any rounding discrepancy
        discrepancy = round(amount - total_allocated, 2)
        if discrepancy != 0:
            # Add the discrepancy to the member with the highest percentage
            max_percentage_member = max(self.percentages.items(), key=lambda x: x[1])[0]
            if max_percentage_member in shares:
                shares[max_percentage_member] = round(shares[max_percentage_member] + discrepancy, 2)
        return shares

    @staticmethod
    def validate_percentages(percentages: Dict[int, float]) -> None:
        """Validate that the provided percentages sum to 100."""
        total = sum(percentages.values())
        if abs(total - 100) > 0.01:  # Using small epsilon for float comparison
            raise ValueError(f"Percentages must sum to 100, got {total}")


class ExactAmountsSplit(SplitStrategy):
    def __init__(self, amounts: Dict[int, float]):
        """Initialize an exact-amounts split strategy.

        Args:
            amounts: Dictionary mapping member IDs to their exact share in dollars
        """
        if not amounts:
            raise ValueError("amounts must be non-empty")
        if any(v < 0 for v in amounts.values()):
            raise ValueError("amounts must be non-negative")
        self.amounts = {int(k): float(v) for k, v in amounts.items()}

    def calculate_shares(self, amount: float, members: list["Member"]) -> Dict[int, float]:
        """Return the pre-specified amounts per member, validating they sum to total."""
        total = sum(self.amounts.values())
        if abs(total - amount) > 0.01:
            raise ValueError(f"amounts must sum to {amount}, got {total}")
        return {m.id: round(self.amounts.get(m.id, 0.0), 2) for m in members}
