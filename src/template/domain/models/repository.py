"""Repository interface"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

from .models import Expense, MonthlyShare


class ExpenseRepository(ABC):
    @abstractmethod
    def add(self, expense: Expense, monthly_share_id: int) -> None:
        """Save an expense"""

    @abstractmethod
    def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
        """Save a monthly share and its expenses"""

    @abstractmethod
    def get_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Get a monthly share by year and month"""

    @abstractmethod
    def get_all_monthly_shares(self) -> Dict[str, MonthlyShare]:
        """Get all monthly shares"""

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
    def settle_monthly_share(self, year: int, month: int) -> None:
        """Settle a Monthly Share"""
