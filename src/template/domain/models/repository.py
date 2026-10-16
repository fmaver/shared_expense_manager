"""Repository interface"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

from .models import Expense, MonthlyShare


class ExpenseRepository(ABC):
    @abstractmethod
    def add(self, expense: Expense, monthly_share_id: int, group_id: int) -> None:
        """Save an expense"""

    @abstractmethod
    def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
        """Save a monthly share and its expenses"""

    @abstractmethod
    def get_monthly_share(self, year: int, month: int, group_id: int) -> Optional[MonthlyShare]:
        """Get a monthly share by year, month and group"""

    def has_monthly_share(self, year: int, month: int, group_id: int) -> bool:
        """Whether the month exists, without loading it."""
        return self.get_monthly_share(year, month, group_id) is not None

    def get_monthly_share_for_update(self, year: int, month: int, group_id: int) -> MonthlyShare:
        """Get-or-create a monthly share and lock it until the next commit.

        Writers that decide on a month's state (add an expense, settle) go through here, so two
        of them on the same group and month run one after the other. This default has no lock:
        it serves in-memory repositories, where there is no concurrency to guard against.
        """
        monthly_share = self.get_monthly_share(year, month, group_id)
        if monthly_share is None:
            self.save_monthly_share(MonthlyShare(year, month, group_id))
            monthly_share = self.get_monthly_share(year, month, group_id)
            if monthly_share is None:
                raise ValueError("Failed to create monthly share")
        return monthly_share

    @abstractmethod
    def get_all_monthly_shares(self, group_id: int) -> Dict[str, MonthlyShare]:
        """Get all monthly shares for a group"""

    @abstractmethod
    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Get an expense by ID."""

    @abstractmethod
    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense by ID."""

    @abstractmethod
    def get_child_expenses(self, parent_expense_id: int) -> List[Expense]:
        """Get all child expenses for a given parent expense ID."""

    @abstractmethod
    def get_expenses_by_date(self, specific_date: date) -> List[Expense]:
        """Get expenses for a particular date"""

    @abstractmethod
    def update_expense(self, expense: Expense) -> None:
        """Update an expense"""

    @abstractmethod
    def settle_monthly_share(self, year: int, month: int, group_id: int) -> None:
        """Settle a Monthly Share"""

    @abstractmethod
    def reassign_expense_to_monthly_share(self, expense_id: int, year: int, month: int, group_id: int) -> None:
        """Move an expense to the monthly share identified by group/year/month."""

    def unsettle_monthly_share(self, year: int, month: int, group_id: int) -> None:
        """Reverse a settlement: delete balancing expenses and mark as unsettled."""

    def find_similar_expenses(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        group_id: int,
        year: int,
        month: int,
        amount: float,
        description: str,
        expense_date: date,
        currency: str = "ARS",
    ) -> List[Expense]:
        """Find parent expenses matching amount + description (case-insensitive) or amount + date."""
        return []
