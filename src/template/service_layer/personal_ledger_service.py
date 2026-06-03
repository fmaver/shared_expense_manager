"""PersonalLedgerService — computes a member's personal financial ledger for a given month."""

from template.adapters.repositories import GroupRepository, IncomeRepository
from template.domain.models.category import Category
from template.domain.models.income import IncomeInstance
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import (
    ExactAmountsSplit,
    PercentageSplit,
    SplitStrategy,
)
from template.domain.schemas.expense import ExpenseResponse, SplitStrategySchema
from template.domain.schemas.income import (
    GroupBalanceItem,
    IncomeInstanceResponse,
    MirroredShareItem,
    PersonalLedgerResponse,
)
from template.service_layer.group_service import GroupService


def _strategy_to_schema(strategy: SplitStrategy) -> SplitStrategySchema:
    """Convert a domain SplitStrategy to its schema representation."""
    if isinstance(strategy, PercentageSplit):
        return SplitStrategySchema(type="percentage", percentages=strategy.percentages)
    if isinstance(strategy, ExactAmountsSplit):
        return SplitStrategySchema(type="exact", amounts=strategy.amounts)
    # EqualSplit — with or without participant_ids
    return SplitStrategySchema(
        type="equal",
        participant_ids=getattr(strategy, "participant_ids", None),
    )


class PersonalLedgerService:
    """Computes a member's personal financial ledger for a given month.

    The ledger aggregates:
    - Income instances (recurring snapshots + variable entries) for the month
    - Direct personal expenses logged in the member's personal group
    - Mirrored shares from the member's other (regular) groups
    """

    def __init__(
        self,
        group_service: GroupService,
        group_repo: GroupRepository,
        expense_repo: ExpenseRepository,
        income_repo: IncomeRepository,
    ):
        self._group_service = group_service
        self._group_repo = group_repo
        self._expense_repo = expense_repo
        self._income_repo = income_repo

    def get_ledger(  # pylint: disable=too-many-locals
        self, owner_member_id: int, year: int, month: int
    ) -> PersonalLedgerResponse:
        """Compute the personal financial ledger for owner_member_id for (year, month).

        Steps:
        A. Resolve (get-or-create) the owner's personal group.
        B. Materialize recurring income snapshots for this month.
        C. Load income instances and sum them.
        D. Load direct personal expenses (expenses in the personal group itself).
        E. Compute mirrored shares from the owner's OTHER groups.
        F. Compute balance totals and return PersonalLedgerResponse.
        """
        # Step A: resolve personal group
        personal_group = self._group_service.get_or_create_personal_group(owner_member_id)

        # Step B: materialize recurring income for this month
        self._materialize_recurring_income(personal_group.id, owner_member_id, year, month)

        # Step C: load income instances
        income_instances = self._income_repo.list_instances_for_month(personal_group.id, year, month)
        total_income = round(sum(i.amount for i in income_instances), 2)
        incomes_response = [self._income_instance_to_response(i) for i in income_instances]

        # Step D: direct personal expenses (expenses logged directly in the personal group)
        personal_share = self._expense_repo.get_monthly_share(year, month, personal_group.id)
        personal_expenses_list: list[ExpenseResponse] = []
        total_personal_expenses = 0.0
        if personal_share:
            for exp in personal_share.expenses:
                # Defensively exclude internal categories (shouldn't exist in personal group, but safe)
                if not Category.is_internal_category(exp.category.name):
                    total_personal_expenses += exp.amount
                    personal_expenses_list.append(
                        ExpenseResponse(
                            id=exp.id,
                            description=exp.description,
                            amount=exp.amount,
                            date=exp.date,
                            category=exp.category.name,
                            payer_id=exp.payer_id,
                            payment_type=exp.payment_type,
                            installments=exp.installments,
                            installment_no=exp.installment_no,
                            split_strategy=_strategy_to_schema(exp.split_strategy),
                            parent_expense_id=exp.parent_expense_id,
                        )
                    )
        total_personal_expenses = round(total_personal_expenses, 2)

        # Step E: mirrored shares + net group balances from OTHER groups
        mirrored_shares: list[MirroredShareItem] = []
        group_balances: list[GroupBalanceItem] = []
        other_groups = self._group_repo.list_for_member(owner_member_id, include_personal=False)
        for source_group in other_groups:
            source_share = self._expense_repo.get_monthly_share(year, month, source_group.id)
            if not source_share:
                continue

            # Net group balance for this owner: positive = creditor, negative = debtor
            net_balance = round(source_share.balances.get(str(owner_member_id), 0.0), 2)
            group_balances.append(
                GroupBalanceItem(
                    source_group_id=source_group.id,
                    source_group_name=source_group.name,
                    net_balance=net_balance,
                    is_settled=source_share.is_settled,
                )
            )

            if not source_share.expenses:
                continue
            # Only fetch members if there are expenses to process
            members_list = self._group_repo.list_members(source_group.id)
            members_dict = {m.id: m for m in members_list}
            for expense in source_share.expenses:
                # Skip internal categories (balance/prestamo)
                if Category.is_internal_category(expense.category.name):
                    continue
                # Compute this owner's share
                try:
                    shares = expense.split_strategy.calculate_shares(expense.amount, list(members_dict.values()))
                except ValueError:
                    # Skip expenses whose stored split data fails validation (e.g., float drift)
                    continue
                owner_share = shares.get(owner_member_id, 0.0)
                if owner_share < 0.005:
                    continue  # owner not a participant in this expense
                status = "realized" if source_share.is_settled else "pending"
                mirrored_shares.append(
                    MirroredShareItem(
                        source_group_id=source_group.id,
                        source_group_name=source_group.name,
                        source_expense_id=expense.id,
                        description=expense.description,
                        category=expense.category.name,
                        date=expense.date,
                        share_amount=round(owner_share, 2),
                        status=status,
                        installment_no=expense.installment_no,
                        installments=expense.installments,
                    )
                )

        # Step F: compute balances
        # Gross shares kept for display context in mirrored shares list
        total_shares_pending = round(sum(s.share_amount for s in mirrored_shares if s.status == "pending"), 2)
        total_shares_realized = round(sum(s.share_amount for s in mirrored_shares if s.status == "realized"), 2)
        # Net group balance across unsettled groups (signed):
        # positive = you'll receive at settlement, negative = you'll pay
        pending_settlements_total = round(sum(gb.net_balance for gb in group_balances if not gb.is_settled), 2)
        # projected = income − direct − settled_costs + pending_net
        # Converges to realized when all groups are settled (pending_settlements_total → 0)
        projected_balance = round(
            total_income - total_personal_expenses - total_shares_realized + pending_settlements_total, 2
        )
        realized_balance = round(total_income - total_personal_expenses - total_shares_realized, 2)

        return PersonalLedgerResponse(
            year=year,
            month=month,
            total_income=total_income,
            incomes=incomes_response,
            total_personal_expenses=total_personal_expenses,
            personal_expenses=personal_expenses_list,
            total_shares_pending=total_shares_pending,
            total_shares_realized=total_shares_realized,
            mirrored_shares=mirrored_shares,
            group_balances=group_balances,
            projected_balance=projected_balance,
            realized_balance=realized_balance,
            pending_settlements_total=pending_settlements_total,
        )

    def _materialize_recurring_income(
        self, personal_group_id: int, owner_member_id: int, year: int, month: int
    ) -> None:
        """Ensure all active recurring income templates have a snapshot for (group, year, month).

        Idempotent: existing snapshots are never overwritten (forward-only semantics).
        """
        templates = self._income_repo.list_recurring(personal_group_id, active_only=True)
        for template in templates:
            # Respect the template's start month — don't backfill past months
            if template.start_year and template.start_month:
                if (year, month) < (template.start_year, template.start_month):
                    continue
            self._income_repo.upsert_recurring_instance(
                personal_group_id=personal_group_id,
                owner_member_id=owner_member_id,
                year=year,
                month=month,
                recurring_income_id=template.id,
                label=template.label,
                amount=template.amount,
            )

    @staticmethod
    def _income_instance_to_response(instance: IncomeInstance) -> IncomeInstanceResponse:
        return IncomeInstanceResponse(
            id=instance.id,
            personal_group_id=instance.personal_group_id,
            owner_member_id=instance.owner_member_id,
            year=instance.year,
            month=instance.month,
            source=instance.source,
            recurring_income_id=instance.recurring_income_id,
            label=instance.label,
            amount=instance.amount,
        )
