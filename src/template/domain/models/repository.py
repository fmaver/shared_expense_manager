"""Repository interface"""
from abc import ABC, abstractmethod
from typing import Dict, Optional

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
