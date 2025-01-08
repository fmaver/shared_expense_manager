"""Expense schemas."""

from datetime import date
from typing import Dict, Optional

from pydantic import Field

from template.domain.models.enums import PaymentType
from template.domain.schema_model import CamelCaseModel


class SplitStrategySchema(CamelCaseModel):
    type: str = Field(..., pattern="^(equal|percentage)$")
    percentages: Optional[Dict[int, float]] = None


class CategorySchema(CamelCaseModel):
    name: str = Field(..., min_length=1)


class CategoryResponse(CamelCaseModel):
    categories: list[str]


class ExpenseCreate(CamelCaseModel):
    description: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    date: date
    category: CategorySchema
    payer_id: int
    payment_type: PaymentType
    installments: int = Field(default=1, ge=1)
    split_strategy: SplitStrategySchema


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


class MonthlyBalanceResponse(CamelCaseModel):
    year: int
    month: int
    expenses: list[ExpenseResponse]
    balances: Dict[int, float]
    is_settled: bool = False
