"""Domain models for income tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field

from ..schema_model import CamelCaseModel


class RecurringIncome(CamelCaseModel):
    """Editable salary / income template that generates monthly snapshots."""

    id: Optional[int] = None
    owner_member_id: int
    personal_group_id: int
    label: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IncomeInstance(CamelCaseModel):
    """Per-month income entry — either a recurring snapshot or a one-off variable income."""

    id: Optional[int] = None
    personal_group_id: int
    year: int
    month: int
    source: Literal["recurring", "variable"]
    recurring_income_id: Optional[int] = None
    label: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
