"""Service layer module for managing expenses and expense-related operations."""

from datetime import date
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta

from template.adapters.orm import ExpenseModel
from template.domain.models.category import Category
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.group import GroupType
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare, PaymentType
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import (
    EqualSplit,
    ExactAmountsSplit,
    PercentageSplit,
    SplitStrategy,
)
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    SplitStrategySchema,
)


def _build_split_strategy(schema: SplitStrategySchema) -> SplitStrategy:
    """Construct the appropriate SplitStrategy from a schema."""
    if schema.type == "percentage":
        if not schema.percentages:
            raise ValueError("Percentages required for percentage split strategy")
        return PercentageSplit(schema.percentages)
    if schema.type == "exact":
        if not schema.amounts:
            raise ValueError("Amounts required for exact split strategy")
        return ExactAmountsSplit(schema.amounts)
    return EqualSplit(participant_ids=schema.participant_ids)


def _strategy_to_schema(strategy: SplitStrategy) -> SplitStrategySchema:
    """Convert a domain SplitStrategy back to its schema representation."""
    if isinstance(strategy, PercentageSplit):
        return SplitStrategySchema(type="percentage", percentages=strategy.percentages)
    if isinstance(strategy, ExactAmountsSplit):
        return SplitStrategySchema(type="exact", amounts=strategy.amounts)
    # EqualSplit — with or without participant_ids
    return SplitStrategySchema(
        type="equal",
        participant_ids=getattr(strategy, "participant_ids", None),
    )


class ExpenseService:
    """Service class for managing expenses."""

    def __init__(self, repository: ExpenseRepository, group_id: int, group_repo):
        """Initialize the expense service."""
        self._repository = repository
        self._group_id = group_id
        self._group_repo = group_repo
        self._manager = ExpenseManager(repository, group_id, group_repo)

    @property
    def group_id(self) -> int:
        """Return the group ID this service is scoped to."""
        return self._group_id

    def get_group_name(self) -> Optional[str]:
        """Return the name of this service's group."""
        group = self._group_repo.get(self._group_id)
        return group.name if group else None

    def get_multi_group_member_ids(self, members: List[Member]) -> set:
        """Return the set of member IDs that belong to more than one group."""
        return {m.id for m in members if len(self._group_repo.list_for_member(m.id)) > 1}

    def is_personal_group(self) -> bool:
        """Return True if the expense service is scoped to a personal group."""
        group = self._group_repo.get(self._group_id)
        return group is not None and group.group_type == GroupType.PERSONAL

    def create_expense(self, expense_data: ExpenseCreate) -> Expense:
        """Create a new expense."""
        category = Category()
        category.name = expense_data.category.name

        expense = Expense(
            description=expense_data.description,
            amount=expense_data.amount,
            date=expense_data.date,
            category=category,
            payer_id=expense_data.payer_id,
            payment_type=expense_data.payment_type,
            installments=expense_data.installments,
            split_strategy=_build_split_strategy(expense_data.split_strategy),
            currency=getattr(expense_data, "currency", "ARS") or "ARS",
        )

        return self._manager.create_and_add_expense(expense)

    def find_similar_expenses(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self, year: int, month: int, amount: float, description: str, expense_date: date
    ) -> List[ExpenseResponse]:
        """Return expenses in the same group/month that may be duplicates of a new entry."""
        expenses = self._repository.find_similar_expenses(
            group_id=self._group_id,
            year=year,
            month=month,
            amount=amount,
            description=description,
            expense_date=expense_date,
        )
        return [
            ExpenseResponse(
                id=e.id,
                description=e.description,
                amount=e.amount,
                date=e.date,
                category=e.category.name,
                payer_id=e.payer_id,
                payment_type=e.payment_type,
                installments=e.installments,
                installment_no=e.installment_no,
                split_strategy=_strategy_to_schema(e.split_strategy),
                parent_expense_id=e.parent_expense_id,
                currency=getattr(e, "currency", "ARS"),
            )
            for e in expenses
        ]

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
                split_strategy=_strategy_to_schema(expense.split_strategy),
                parent_expense_id=expense.parent_expense_id,
                recurring_template_id=expense.recurring_template_id,
                currency=getattr(expense, "currency", "ARS"),
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
        existing_expense = self._manager.get_expense(expense_id)
        if not existing_expense:
            raise ValueError(f"Expense with ID {expense_id} not found.")

        # Guard: child installments cannot be edited directly
        if existing_expense.payment_type == PaymentType.CREDIT and existing_expense.installment_no > 1:
            raise ValueError("Cannot update credit expense installments after the first one")

        # Case 1: existing is already multi-installment credit
        if existing_expense.payment_type == PaymentType.CREDIT and existing_expense.installments > 1:
            # Case 1a: converting to debit — delete all installments, recreate as a single debit row
            if expense_data.payment_type == PaymentType.DEBIT:
                self._manager.delete_expense(expense_id)

                category = Category()
                category.name = expense_data.category.name

                new_expense = Expense(
                    description=expense_data.description,
                    amount=expense_data.amount,
                    date=expense_data.date,
                    category=category,
                    payer_id=expense_data.payer_id,
                    payment_type=PaymentType.DEBIT,
                    installments=1,
                    split_strategy=_build_split_strategy(expense_data.split_strategy),
                    currency=getattr(expense_data, "currency", "ARS") or "ARS",
                )
                return self._manager.create_and_add_expense(new_expense)

            # Case 1b: credit → credit (any number of installments) — update in place
            category = Category()
            category.name = expense_data.category.name

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
                split_strategy=_build_split_strategy(expense_data.split_strategy),
                parent_expense_id=existing_expense.parent_expense_id,
                currency=getattr(expense_data, "currency", "ARS") or "ARS",
            )
            return self._manager.update_credit_expense(updated_expense)

        # Case 2: converting to multi-installment credit (debit→credit-N or credit-1→credit-N)
        # Delete the old single-row expense and recreate using the full credit creation path
        if expense_data.payment_type == PaymentType.CREDIT and expense_data.installments > 1:
            self._manager.delete_expense(expense_id)

            category = Category()
            category.name = expense_data.category.name

            new_expense = Expense(
                description=expense_data.description,
                amount=expense_data.amount,
                date=expense_data.date,
                category=category,
                payer_id=expense_data.payer_id,
                payment_type=expense_data.payment_type,
                installments=expense_data.installments,
                split_strategy=_build_split_strategy(expense_data.split_strategy),
                currency=getattr(expense_data, "currency", "ARS") or "ARS",
            )
            return self._manager.create_and_add_expense(new_expense)

        # Case 3: simple update — debit↔debit, debit↔credit-1, credit-1↔credit-1, credit-1→debit
        # Capture old location before mutating so update_expense can move between shares
        old_payment_type = existing_expense.payment_type
        old_date = existing_expense.date

        existing_expense.description = expense_data.description
        existing_expense.amount = expense_data.amount
        existing_expense.date = expense_data.date
        existing_expense.category.name = expense_data.category.name
        existing_expense.payer_id = expense_data.payer_id
        existing_expense.payment_type = expense_data.payment_type
        existing_expense.installments = expense_data.installments
        existing_expense.split_strategy = _build_split_strategy(expense_data.split_strategy)
        existing_expense.currency = getattr(expense_data, "currency", "ARS") or "ARS"

        return self._manager.update_expense(existing_expense, old_payment_type, old_date)

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

    def unsettle_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Reverse a settlement: delete balancing expenses and reopen the month."""
        monthly_share = self._manager.unsettle_monthly_share(year, month)
        if not monthly_share:
            raise ValueError(f"No monthly share found for {year}-{month}.")
        return monthly_share

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

    def get_group_trend(self, months: int = 6) -> List[Dict]:
        """Return per-month expense totals for the last N months (excluding balance category)."""
        today = date.today()
        start = today - relativedelta(months=months - 1)
        start_date = date(start.year, start.month, 1)

        session = self._repository.session
        rows = (
            session.query(ExpenseModel)
            .filter(
                ExpenseModel.group_id == self._group_id,
                ExpenseModel.category != "balance",
                ExpenseModel.parent_expense_id.is_(None),
                ExpenseModel.date >= start_date,
            )
            .all()
        )

        buckets: Dict[tuple, Dict] = {}
        for row in rows:
            key = (row.date.year, row.date.month)
            if key not in buckets:
                buckets[key] = {"year": key[0], "month": key[1], "total": 0.0, "by_category": {}, "by_payer": {}}
            b = buckets[key]
            b["total"] += row.amount
            b["by_category"][row.category] = b["by_category"].get(row.category, 0.0) + row.amount
            payer_key = str(row.payer_id)
            b["by_payer"][payer_key] = b["by_payer"].get(payer_key, 0.0) + row.amount

        return sorted(buckets.values(), key=lambda x: (x["year"], x["month"]))
