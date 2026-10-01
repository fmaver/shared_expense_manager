"""Search and unsettled-month response schemas."""

from datetime import date
from typing import Literal, Optional

from template.domain.schema_model import CamelCaseModel


class UnsettledMonth(CamelCaseModel):
    """A past month of a group that was left unsettled."""

    year: int
    month: int


class ExpenseSearchResult(CamelCaseModel):
    """One expense row (one installment) or one personal fixed-expense month that matched."""

    kind: Literal["expense", "recurring_personal"]
    id: int
    parent_expense_id: Optional[int]
    description: str
    amount: float
    currency: str
    your_share: Optional[float]
    date: Optional[date]
    category: str
    group_id: int
    group_name: str
    group_type: str
    payer_id: Optional[int]
    payer_name: str
    installment_no: int
    installments: int
    period_year: int
    period_month: int
    period_settled: Optional[bool]


class ExpenseSearchResponse(CamelCaseModel):
    results: list[ExpenseSearchResult]
    has_more: bool
