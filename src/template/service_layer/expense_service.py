"""Service layer module for managing expenses and expense-related operations."""

from typing import Dict, List, Optional

from template.domain.models.category import Category
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare, PaymentType
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

    def create_expense(self, expense_data: ExpenseCreate) -> Expense:
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

        return self._manager.create_and_add_expense(expense)

    def get_monthly_balance(self, year: int, month: int) -> MonthlyShare:
        """Get monthly balances"""
        monthly_share = self._manager.get_monthly_balance(year, month)
        if not monthly_share:
            return {}

        return monthly_share

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
                parent_expense_id=expense.parent_expense_id,
            )
            for expense in monthly_share.expenses
        ]

    def get_member_names(self) -> Dict[int, str]:
        """Devuelve un diccionario de miembros con su ID como clave y nombre como valor."""
        return {member.id: member.name for member in self._manager.members.values()}

    def get_members(self) -> List[Member]:
        """Devuelve una lista de miembros."""
        return list(self._manager.members.values())

    def update_expense(self, expense_id: int, expense_data: ExpenseCreate) -> Expense:
        """Update an existing expense."""
        # Fetch the existing expense from the repository
        existing_expense = self._manager.get_expense(expense_id)
        if not existing_expense:
            raise ValueError(f"Expense with ID {expense_id} not found.")

        # For credit expenses with installments, only allow updating the first installment
        if existing_expense.payment_type == PaymentType.CREDIT and existing_expense.installments > 1:
            if existing_expense.installment_no > 1:
                raise ValueError("Cannot update credit expense installments after the first one")

            # Create a new expense object with updated data
            category = Category()
            category.name = expense_data.category.name

            # Create appropriate split strategy based on type
            if expense_data.split_strategy.type == "percentage":
                if not expense_data.split_strategy.percentages:
                    raise ValueError("Percentages required for percentage split strategy")
                split_strategy = PercentageSplit(expense_data.split_strategy.percentages)
            else:
                split_strategy = EqualSplit()

            updated_expense = Expense(
                id=existing_expense.id,
                description=expense_data.description,
                amount=expense_data.amount,
                date=expense_data.date,
                category=category,
                payer_id=expense_data.payer_id,
                payment_type=expense_data.payment_type,
                installments=expense_data.installments,
                installment_no=existing_expense.installment_no,
                split_strategy=split_strategy,
                parent_expense_id=existing_expense.parent_expense_id,
            )

            # Update the expense and its related installments
            return self._manager.update_credit_expense(updated_expense)

        # For non-credit or single installment expenses, proceed with normal update
        existing_expense.description = expense_data.description
        existing_expense.amount = expense_data.amount
        existing_expense.date = expense_data.date
        existing_expense.category.name = expense_data.category.name
        existing_expense.payer_id = expense_data.payer_id
        existing_expense.payment_type = expense_data.payment_type

        # Update split strategy
        if expense_data.split_strategy.type == "percentage":
            if not expense_data.split_strategy.percentages:
                raise ValueError("Percentages required for percentage split strategy")
            existing_expense.split_strategy = PercentageSplit(expense_data.split_strategy.percentages)
        else:
            existing_expense.split_strategy = EqualSplit()

        return self._manager.update_expense(existing_expense)

    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense."""
        self._manager.delete_expense(expense_id)

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Get an expense by ID."""
        expense = self._manager.get_expense(expense_id)
        if not expense:
            raise ValueError(f"Expense with ID {expense_id} not found.")

        return expense

    def get_parent_expense(self, expense_id: int) -> Optional[Expense]:
        """Get the parent expense for a given expense ID."""
        return self._manager.get_parent_expense(expense_id)

    def settle_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Settle a monthly share - resolve balances."""
        monthly_share = self._manager.settle_monthly_share(year, month)
        if not monthly_share:
            raise ValueError(f"No monthly share found for {year}-{month}.")

        return monthly_share

    def recalculate_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Recalculate a monthly share - resolve balances."""

        monthly_share = self._manager.get_monthly_balance(year, month)

        if not monthly_share:
            raise ValueError(f"No monthly share found for {year}-{month}.")

        return self._manager.recalculate_monthly_share(monthly_share)
