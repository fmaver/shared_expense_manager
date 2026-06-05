"""Service layer for recurring group expense templates and lazy materialization."""

from datetime import date

from template.adapters.repositories import RecurringGroupExpenseRepository, SQLAlchemyExpenseRepository
from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.models import Expense
from template.service_layer.expense_service import _build_split_strategy


def materialize_recurring_group_expenses(
    group_id: int,
    year: int,
    month: int,
    recurring_repo: RecurringGroupExpenseRepository,
    expense_repo: SQLAlchemyExpenseRepository,
    expense_manager: ExpenseManager,
) -> None:
    """Lazily materialize recurring group expenses for (group_id, year, month).

    Called each time a monthly share is read (lazy/on-view pattern).

    For each active template whose start date is on or before (year, month):
    - Checks the idempotency guard; skips if already materialized.
    - Creates a real Expense row via ExpenseManager and tags it with the template id.

    Idempotent: safe to call multiple times for the same (group_id, year, month).
    Skips settled months entirely: returns early if the month is settled.
    """
    # Check if the month is settled before processing any templates.
    # get_monthly_balance returns None when no share exists yet (unsettled by definition).
    existing_share = expense_manager.get_monthly_balance(year, month)
    if existing_share is not None and existing_share.is_settled:
        return

    templates = recurring_repo.list_for_group(group_id, active_only=True)

    for template in templates:
        # Skip templates that haven't started yet
        if (template.start_year, template.start_month) > (year, month):
            continue

        # Idempotency guard: try to insert the instance record.
        # Returns False when the instance already exists → skip to avoid duplicates.
        newly_created = recurring_repo.upsert_instance(template.id, group_id, year, month)
        if not newly_created:
            continue

        # Build the domain Expense from the template
        category = Category()
        category.name = template.category

        expense = Expense(
            description=template.description,
            amount=template.amount,
            date=date(year, month, 1),
            category=category,
            payer_id=template.payer_id,
            installments=1,
            installment_no=1,
            payment_type=PaymentType(template.payment_type),
            split_strategy=_build_split_strategy(template.split_strategy),
        )

        # Add to the monthly share (creates the row in DB and recalculates balances).
        # _add_to_monthly_share sets expense.id after saving.
        expense_manager._add_to_monthly_share(expense, date(year, month, 1))  # pylint: disable=protected-access

        # Tag the saved expense row with the originating template id.
        if expense.id is not None:
            expense_repo.set_recurring_template_id(expense.id, template.id)
