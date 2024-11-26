"""Service layer module for managing expenses and expense-related operations."""

from typing import List

from template.domain.models.category import Category
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.models import Expense
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    SplitStrategySchema,
)


class ExpenseService:
    """Service class for managing expenses."""

    def __init__(self, repository: ExpenseRepository):
        """Initialize the expense service."""
        self._manager = ExpenseManager(repository)

    def create_expense(self, expense_data: ExpenseCreate) -> None:
        """Create a new expense."""
        category = Category()
        category.name = expense_data.category.name

        # Create appropriate split strategy based on type
        if expense_data.split_strategy.type == "percentage":
            if not expense_data.split_strategy.percentages:
                raise ValueError("Percentages required for percentage split strategy")
            split_strategy = PercentageSplit(expense_data.split_strategy.percentages)
        else:
            split_strategy = EqualSplit()

        expense = Expense(
            description=expense_data.description,
            amount=expense_data.amount,
            date=expense_data.date,
            category=category,
            payer_id=expense_data.payer_id,
            payment_type=expense_data.payment_type,
            installments=expense_data.installments,
            split_strategy=split_strategy,
        )

        self._manager.create_and_add_expense(expense)

    def get_monthly_expenses(self, year: int, month: int) -> List[ExpenseResponse]:
        """Get monthly expenses."""
        monthly_share = self._manager.get_monthly_balance(year, month)
        if not monthly_share:
            return []

        return [
            ExpenseResponse(
                id=expense.id,
                description=expense.description,
                amount=expense.amount,
                date=expense.date,
                category=expense.category.name,
                payer_id=expense.payer_id,
                installments=expense.installments,
                installment_no=expense.installment_no,
                payment_type=expense.payment_type,
                split_strategy=SplitStrategySchema(
                    type="equal" if isinstance(expense.split_strategy, EqualSplit) else "percentage",
                    percentages=getattr(expense.split_strategy, "percentages", None),
                ),
            )
            for expense in monthly_share.expenses
        ]
