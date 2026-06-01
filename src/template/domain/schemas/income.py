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
# Ledger
# ---------------------------------------------------------------------------


class MirroredShareItem(CamelCaseModel):
    source_group_id: int
    source_group_name: str
    source_expense_id: int
    description: str
    category: str
    date: date
    share_amount: float
    status: Literal["pending", "realized"]


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
    projected_balance: float
    realized_balance: float
    pending_settlements_total: float
