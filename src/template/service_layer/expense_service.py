"""Service layer module for managing expenses and expense-related operations."""

from typing import List

from template.domain.models.category import Category
from template.domain.models.models import Expense, ExpenseManager
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schemas.expense import ExpenseCreate, ExpenseResponse


class ExpenseService:
    """Service class for managing expenses."""

    def __init__(self):
        """Initialize the expense service."""
        self._manager = ExpenseManager()

    def create_expense(self, expense_data: ExpenseCreate) -> None:
        """Create a new expense."""
        category = Category()
        category.name = expense_data.category

        split_strategy = (
            PercentageSplit(expense_data.split_percentages) if expense_data.split_percentages else EqualSplit()
        )

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
            )
            for expense in monthly_share.expenses
        ]
