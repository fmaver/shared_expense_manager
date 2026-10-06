"""Domain models for the expense sharing application."""

from datetime import date
from typing import Dict, List, Optional, Tuple

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
    recurring_template_id: Optional[int] = None
    currency: str = "ARS"  # "ARS" or "USD"

    @field_validator("installment_no")
    def validate_installment_no(cls, v: int, info: ValidationInfo) -> int:
        """Validate that installment number is not greater than total installments."""
        context = info.context or {}
        installments = context.get("installments")
        if installments is not None and v > installments:
            raise ValueError("Installment number cannot be greater than total installments")
        return v


def expense_shares_in_ars(
    expense: Expense, members: List[Member], usd_rate: float = 1.0
) -> Tuple[float, Dict[int, float]]:
    """Return (paid, shares per member) for an expense, both in ARS.

    The split runs in the expense's own currency — an exact split of a USD expense lists
    dollars, so it has to be checked against the dollar total — and only then is each part
    converted. Whatever the parts miss the paid amount by goes to the largest part, so a
    month's balances still net to zero: cents from rounding, and also the up-to-US$0.01 an
    exact split is allowed to be off, which at the blue rate is over AR$10.
    """
    shares = expense.split_strategy.calculate_shares(expense.amount, members)
    if getattr(expense, "currency", "ARS") != "USD":
        return expense.amount, shares

    paid = round(expense.amount * usd_rate, 2)
    converted = {member_id: round(share * usd_rate, 2) for member_id, share in shares.items()}
    residual = round(paid - sum(converted.values()), 2)
    if converted and residual:
        largest = max(converted, key=lambda member_id: converted[member_id])
        converted[largest] = round(converted[largest] + residual, 2)
    return paid, converted


class MonthlyShare:
    def __init__(self, year: int, month: int, group_id: int = 0):
        self.year = year
        self.month = month
        self.group_id = group_id
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

    def add_expense(self, expense: Expense, members: Dict[int, Member], usd_rate: float = 1.0) -> None:
        """Adds an expense and updates balances accordingly"""
        if self.is_settled:
            raise ValueError(f"No se puede agregar el gasto al balance de {self.month}-{self.year} ya que está saldado")

        # Recalculate balances
        self.calculate_share_for_expense(expense, members, usd_rate=usd_rate)

        # Add expense to the list
        self.expenses.append(expense)

    def recalculate_balances(self, members: Dict[int, Member], usd_rate: float = 1.0) -> None:
        """Recalculates all balances from scratch with the current expenses"""
        if self.is_settled:
            return

        # Reset all balances
        self.balances = {}

        # Recalculate for each expense
        for expense in self.expenses:
            self.calculate_share_for_expense(expense, members, usd_rate=usd_rate)

        # A balance can belong to someone who already left the group: fall back to the id.
        for member_id, balance in self.balances.items():
            member = members.get(int(member_id))
            print(f"{member.name if member else member_id}: {balance}")

    def calculate_share_for_expense(self, expense: Expense, members: Dict[int, Member], usd_rate: float = 1.0) -> None:
        """Calculates the share for a specific expense, in ARS (see expense_shares_in_ars)."""
        amount, shares = expense_shares_in_ars(expense, list(members.values()), usd_rate)

        # Add what the payer paid
        payer_id_str = str(expense.payer_id)
        self.balances.setdefault(payer_id_str, 0)
        self.balances[payer_id_str] = round(self.balances[payer_id_str] + amount, 2)

        # Subtract each member's share (including the payer)
        for member_id, share in shares.items():
            member_id_str = str(member_id)
            self.balances.setdefault(member_id_str, 0)
            self.balances[member_id_str] = round(self.balances[member_id_str] - share, 2)
        # print(f"Expense {expense.id} recalculated balances: {self.balances}")
