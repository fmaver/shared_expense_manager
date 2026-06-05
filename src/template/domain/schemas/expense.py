"""Expense schemas."""

from datetime import date
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from template.domain.models.enums import PaymentType
from template.domain.schema_model import CamelCaseModel


class SplitStrategySchema(CamelCaseModel):
    type: str = Field(..., pattern="^(equal|percentage|exact)$")
    percentages: Optional[Dict[int, float]] = None
    participant_ids: Optional[List[int]] = None
    amounts: Optional[Dict[int, float]] = None


class CategorySchema(CamelCaseModel):
    name: str = Field(..., min_length=1)


class CategoryResponse(CamelCaseModel):
    categories: list[str]


class CategoryWithEmojiResponse(CamelCaseModel):
    """Response model for categories with emojis."""

    name: str
    emoji: str


class ExpenseCreate(CamelCaseModel):
    description: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    date: date
    category: CategorySchema
    payer_id: int
    payment_type: PaymentType
    installments: int = Field(default=1, ge=1)
    split_strategy: SplitStrategySchema

    @model_validator(mode="after")
    def validate_exact_amounts_sum(self) -> "ExpenseCreate":
        """Validate that exact-split amounts sum to the expense total."""
        if self.split_strategy.type == "exact":
            if not self.split_strategy.amounts:
                raise ValueError("amounts required for exact split strategy")
            total = sum(self.split_strategy.amounts.values())
            if abs(total - self.amount) > 0.01:
                raise ValueError(f"amounts must sum to {self.amount}, got {total}")
        return self


class ExpenseResponse(CamelCaseModel):
    id: Optional[int] = None
    description: str
    amount: float
    date: date
    category: str
    payer_id: int
    payment_type: PaymentType
    installments: int
    installment_no: int = 1
    split_strategy: SplitStrategySchema
    parent_expense_id: Optional[int] = None
    recurring_template_id: Optional[int] = None


class MonthlyBalanceResponse(CamelCaseModel):
    year: int
    month: int
    expenses: list[ExpenseResponse]
    balances: Dict[int, float]
    is_settled: bool = False


# ---------------------------------------------------------------------------
# Recurring group expense schemas
# ---------------------------------------------------------------------------


class RecurringGroupExpenseCreate(CamelCaseModel):
    description: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category: str = Field(..., min_length=1, max_length=50)
    payer_id: int
    payment_type: PaymentType
    split_strategy: SplitStrategySchema
    start_year: int = Field(..., ge=2000, le=2100)
    start_month: int = Field(..., ge=1, le=12)


class RecurringGroupExpenseUpdate(CamelCaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=255)
    amount: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, min_length=1, max_length=50)
    payer_id: Optional[int] = None
    payment_type: Optional[PaymentType] = None
    split_strategy: Optional[SplitStrategySchema] = None
    start_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    active: Optional[bool] = None


class RecurringGroupExpenseResponse(CamelCaseModel):
    id: int
    group_id: int
    description: str
    amount: float
    category: str
    payer_id: int
    payment_type: PaymentType
    split_strategy: SplitStrategySchema
    start_year: int
    start_month: int
    active: bool
