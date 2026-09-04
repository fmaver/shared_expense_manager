"""Aggregate balances for one-time (occasion) groups.

A one-time group has no notion of "this month": a trip or a dinner is one event. Monthly
shares still exist underneath it — that is what keeps the schema and the balance math
untouched — so this service collapses them into a single expense list and a single balance map
at the edge.

Kept separate from ExpenseService deliberately: that class is already at the limit of what one
unit should do, and "present a group with months collapsed" is its own responsibility.
"""

from typing import Dict, List

from template.domain.models.expense_manager import compute_debt_transfers
from template.domain.models.repository import ExpenseRepository
from template.domain.schemas.expense import (
    AggregateBalanceResponse,
    DebtTransfer,
    ExpenseResponse,
)
from template.service_layer.expense_service import ExpenseService


class OccasionService:
    """Presents a whole group as one balance, ignoring month boundaries."""

    def __init__(self, expense_service: ExpenseService, repository: ExpenseRepository):
        self._expenses = expense_service
        self._repository = repository
        self._group_id = expense_service.group_id

    def get_aggregate_balance(self) -> AggregateBalanceResponse:
        """Collapse every month of this group into one expense list and one balance map.

        Balances are summed per member across months. Sound because they are already stored in
        ARS (USD is converted at recalculation time), so nothing is converted here.
        """
        shares = self._repository.get_all_monthly_shares(self._group_id)
        expenses: List[ExpenseResponse] = []
        balances: Dict[int, float] = {}
        months_with_expenses = 0
        settled_months = 0

        for share in sorted(shares.values(), key=lambda s: (s.year, s.month)):
            if not share.expenses:
                continue
            months_with_expenses += 1
            if share.is_settled:
                settled_months += 1
            expenses.extend(self._expenses.get_monthly_expenses(share.year, share.month))
            for member_id, amount in (share.balances or {}).items():
                key = int(member_id)
                balances[key] = round(balances.get(key, 0.0) + amount, 2)

        transfers = [
            DebtTransfer(from_member_id=d, to_member_id=c, amount=a)
            for d, c, a in compute_debt_transfers({str(k): v for k, v in balances.items()})
        ]
        return AggregateBalanceResponse(
            group_id=self._group_id,
            expenses=expenses,
            balances=balances,
            # All-months, not any-month: one open month means the occasion is not settled.
            is_settled=months_with_expenses > 0 and settled_months == months_with_expenses,
            transfers=transfers,
        )

    def unsettle_all(self) -> AggregateBalanceResponse:
        """Reopen every settled month of this group, then return the aggregate.

        The mirror of settle_all: an occasion is settled as one thing, so it has to be
        reopened as one thing. Reopening only the viewed month would leave the group
        half-settled with no way to tell from the single balance shown.
        """
        shares = self._repository.get_all_monthly_shares(self._group_id)
        for share in sorted(shares.values(), key=lambda s: (s.year, s.month)):
            if share.is_settled:
                self._expenses.unsettle_monthly_share(share.year, share.month)
        return self.get_aggregate_balance()

    def settle_all(self) -> AggregateBalanceResponse:
        """Settle every month of this group that holds expenses, then return the aggregate."""
        shares = self._repository.get_all_monthly_shares(self._group_id)
        for share in sorted(shares.values(), key=lambda s: (s.year, s.month)):
            if share.expenses and not share.is_settled:
                self._expenses.settle_monthly_share(share.year, share.month)
        return self.get_aggregate_balance()
