"""Domain models for the expense sharing application."""

from datetime import date
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta
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
        self.expenses: List[Expense] = []
        self.balances: Dict[int, float] = {}
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

    def unsettle(self) -> None:
        """Mark the monthly share as unsettled."""
        self._is_settled = False

    def add_expense(self, expense: Expense, members: Dict[int, Member]) -> None:
        """Adds an expense and updates balances accordingly"""
        if self.is_settled:
            raise ValueError(f"Cannot add expense to settled period {self.year}-{self.month}")

        # Calculate shares for this specific expense
        shares = expense.split_strategy.calculate_shares(expense.amount, list(members.values()))

        # Update balances
        # Add what others owe to the payer
        self.balances.setdefault(expense.payer_id, 0)
        self.balances[expense.payer_id] += expense.amount

        # Subtract what each member owes
        for member_id, share in shares.items():
            self.balances.setdefault(member_id, 0)
            if member_id != expense.payer_id:
                self.balances[member_id] -= share
            else:
                self.balances[member_id] -= share  # Payer also pays their share

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
            shares = expense.split_strategy.calculate_shares(expense.amount, list(members.values()))

            # Add what others owe to the payer
            self.balances.setdefault(expense.payer_id, 0)
            self.balances[expense.payer_id] += expense.amount

            # Subtract what each member owes
            for member_id, share in shares.items():
                self.balances.setdefault(member_id, 0)
                if member_id != expense.payer_id:
                    self.balances[member_id] -= share
                else:
                    self.balances[member_id] -= share


class ExpenseManager:
    def __init__(self):
        self.members: Dict[int, Member] = {}  # member_id -> Member
        self.monthly_shares: Dict[str, MonthlyShare] = {}  # "YYYY-MM" -> MonthlyShare

    def create_and_add_expense(self, expense: Expense) -> None:
        """
        Creates and adds expense(s) based on payment type and installments.
        For credit payments, creates expenses for future months.
        """
        if expense.payment_type == PaymentType.DEBIT:
            self._add_to_monthly_share(expense, expense.date)
        else:  # CREDIT
            self._handle_credit_expense(expense)

    def _handle_credit_expense(self, expense: Expense) -> None:
        """Handles credit expenses, creating installments as needed"""
        # Calculate amount per installment
        amount_per_installment = expense.amount / expense.installments

        # For credit, payments start next month
        start_date = expense.date + relativedelta(months=1)

        # Create an expense for each installment
        for installment_no in range(1, expense.installments + 1):
            installment_date = start_date + relativedelta(months=installment_no - 1)

            installment_expense = Expense(
                description=f"{expense.description} ({installment_no}/{expense.installments})",
                amount=amount_per_installment,
                date=expense.date,
                category=expense.category,
                payer_id=expense.payer_id,
                payment_type=PaymentType.CREDIT,
                installments=expense.installments,
                installment_no=installment_no,
                split_strategy=expense.split_strategy,
            )

            self._add_to_monthly_share(installment_expense, installment_date)

    def _add_to_monthly_share(self, expense: Expense, share_date: date) -> None:
        """Adds an expense to its corresponding monthly share"""
        period_key = f"{share_date.year}-{share_date.month:02d}"

        # Get or create monthly share
        if period_key not in self.monthly_shares:
            self.monthly_shares[period_key] = MonthlyShare(year=share_date.year, month=share_date.month)

        monthly_share = self.monthly_shares[period_key]
        monthly_share.add_expense(expense, self.members)

    def get_monthly_balance(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Gets the monthly share for a specific period"""
        period_key = f"{year}-{month:02d}"
        return self.monthly_shares.get(period_key)

    def settle_monthly_share(self, year: int, month: int) -> None:
        """Marks a monthly share as settled"""
        period_key = f"{year}-{month:02d}"
        if period_key in self.monthly_shares:
            self.monthly_shares[period_key].settle()

    def add_member(self, member: Member) -> None:
        """Adds a new member and recalculates all active monthly shares"""
        self.members[member.id] = member

        # Recalculate balances for all active monthly shares
        for monthly_share in self.monthly_shares.values():
            if not monthly_share.is_settled:
                monthly_share.recalculate_balances(self.members)
