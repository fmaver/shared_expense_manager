"""Income request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import Field

from template.domain.schema_model import CamelCaseModel
from template.domain.schemas.expense import ExpenseResponse

# ---------------------------------------------------------------------------
# RecurringIncome CRUD
# ---------------------------------------------------------------------------


class RecurringIncomeCreate(CamelCaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    start_year: int = Field(..., ge=2000, le=2100)
    start_month: int = Field(..., ge=1, le=12)


class RecurringIncomeUpdate(CamelCaseModel):
    label: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    active: Optional[bool] = None


class RecurringIncomeResponse(CamelCaseModel):
    id: int
    owner_member_id: int
    personal_group_id: int
    label: str
    amount: float
    active: bool
    start_year: Optional[int] = None
    start_month: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Variable income CRUD
# ---------------------------------------------------------------------------


class VariableIncomeCreate(CamelCaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    label: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)


class VariableIncomeUpdate(CamelCaseModel):
    label: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class IncomeInstanceResponse(CamelCaseModel):
    id: int
    personal_group_id: int
    owner_member_id: int
    year: int
    month: int
    source: Literal["recurring", "variable"]
    recurring_income_id: Optional[int] = None
    label: str
    amount: float


# ---------------------------------------------------------------------------
# RecurringPersonalExpense CRUD
# ---------------------------------------------------------------------------


class RecurringPersonalExpenseCreate(CamelCaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category_name: str = Field(..., min_length=1, max_length=50)
    start_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    start_month: Optional[int] = Field(default=None, ge=1, le=12)


class RecurringPersonalExpenseUpdate(CamelCaseModel):
    label: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    category_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    active: Optional[bool] = None


class RecurringPersonalExpenseResponse(CamelCaseModel):
    id: int
    personal_group_id: int
    owner_member_id: int
    label: str
    amount: float
    category_name: str
    active: bool
    start_year: Optional[int] = None
    start_month: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RecurringPersonalExpenseInstanceResponse(CamelCaseModel):
    id: int
    personal_group_id: int
    recurring_expense_id: int
    year: int
    month: int
    label: str
    amount: float
    category_name: str


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class GroupBalanceItem(CamelCaseModel):
    """Net balance for one group in a given month.

    Positive means the owner is a creditor (will receive money at settlement).
    Negative means the owner is a debtor (will pay money at settlement).
    """

    source_group_id: int
    source_group_name: str
    net_balance: float
    is_settled: bool


class MirroredShareItem(CamelCaseModel):
    source_group_id: int
    source_group_name: str
    source_expense_id: int
    description: str
    category: str
    date: date
    share_amount: float
    status: Literal["pending", "realized"]
    installment_no: int = 1
    installments: int = 1
    # Full amount paid by the owner as payer (0 when someone else paid)
    payer_amount: float = 0.0


class PersonalLedgerResponse(CamelCaseModel):
    year: int
    month: int
    total_income: float
    incomes: list[IncomeInstanceResponse]
    total_personal_expenses: float
    personal_expenses: list[ExpenseResponse]
    total_shares_pending: float
    total_shares_realized: float
    mirrored_shares: list[MirroredShareItem]
    recurring_personal_expenses: list[RecurringPersonalExpenseInstanceResponse] = []
    # Per-group net balance for the month (positive = creditor, negative = debtor)
    group_balances: list[GroupBalanceItem]
    # Money already paid out-of-pocket as payer in unsettled groups
    total_paid_as_payer_unsettled: float
    projected_balance: float
    realized_balance: float
    # Actual cash position right now (before pending settlements clear)
    current_balance: float
    # Net amount across all unsettled groups: positive = you'll receive, negative = you'll pay
    pending_settlements_total: float
