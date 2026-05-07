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


class MonthlyBalanceResponse(CamelCaseModel):
    year: int
    month: int
    expenses: list[ExpenseResponse]
    balances: Dict[int, float]
    is_settled: bool = False
