"""Domain models for the expense sharing application."""

from datetime import date
from typing import Dict, List, Optional

from pydantic import Field, ValidationInfo, field_validator

from ..schema_model import CamelCaseModel
from .category import Category
from .enums import PaymentType
from .member import Member
from .split import SplitStrategy


class Expense(CamelCaseModel):
    model_config = {"arbitrary_types_allowed": True}

    id: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    date: date
    category: Category
    payer_id: int
    installments: int = Field(default=1, ge=1)
    installment_no: int = Field(default=1, ge=1)
    payment_type: PaymentType
    split_strategy: SplitStrategy
    parent_expense_id: Optional[int] = None

    @field_validator("installment_no")
    def validate_installment_no(cls, v: int, info: ValidationInfo) -> int:
        """Validate that installment number is not greater than total installments."""
        context = info.context or {}
        installments = context.get("installments")
        if installments is not None and v > installments:
            raise ValueError("Installment number cannot be greater than total installments")
        return v


class MonthlyShare:
    def __init__(self, year: int, month: int):
        self.year = year
        self.month = month
        self.expenses: List[Expense] = []  # List of expenses for the month
        self.balances: Dict[str, float] = {}  # Member ID -> Balance
        self._is_settled = False

    @property
    def period_key(self) -> str:
        """Return the period key in YYYY-MM format."""
        return f"{self.year}-{self.month:02d}"

    def settle(self) -> None:
        """Changes the settled status of a monthly share"""
        self._is_settled = True

    @property
    def is_settled(self) -> bool:
        """Returns whether the monthly share is settled"""
        return self._is_settled

    @is_settled.setter
    def is_settled(self, value: bool):
        self._is_settled = value

    def unsettle(self) -> None:
        """Mark the monthly share as unsettled."""
        self._is_settled = False

    def add_expense(self, expense: Expense, members: Dict[int, Member]) -> None:
        """Adds an expense and updates balances accordingly"""
        if self.is_settled:
            raise ValueError(f"No se puede agregar el gasto al balance de {self.month}-{self.year} ya que está saldado")

        # Recalculate balances
        self.calculate_share_for_expense(expense, members)

        # Add expense to the list
        self.expenses.append(expense)

    def recalculate_balances(self, members: Dict[int, Member]) -> None:
        """Recalculates all balances from scratch with the current expenses"""
        if self.is_settled:
            return

        # Reset all balances
        self.balances = {}

        # Recalculate for each expense
        for expense in self.expenses:
            self.calculate_share_for_expense(expense, members)

        print(f"Recalculated balances for {self.period_key}: {self.balances}")
        for member_id, balance in self.balances.items():
            print(f"{members[int(member_id)].name}: {balance}")

    def calculate_share_for_expense(self, expense: Expense, members: Dict[int, Member]) -> None:
        """Calculates the share for a specific expense"""
        shares = expense.split_strategy.calculate_shares(expense.amount, list(members.values()))

        # Add what the payer paid
        payer_id_str = str(expense.payer_id)
        self.balances.setdefault(payer_id_str, 0)
        self.balances[payer_id_str] = round(self.balances[payer_id_str] + expense.amount, 2)

        # Subtract each member's share (including the payer)
        for member_id, share in shares.items():
            member_id_str = str(member_id)
            self.balances.setdefault(member_id_str, 0)
            self.balances[member_id_str] = round(self.balances[member_id_str] - share, 2)
        print(f"Expense {expense.id} recalculated balances: {self.balances}")
