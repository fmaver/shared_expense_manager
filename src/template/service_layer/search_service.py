"""Expense search for one member: every group they are in, or one of them."""

import logging
from datetime import date
from typing import Optional

from template.adapters.repositories import GroupRepository, SearchRepository
from template.domain.models.group import GroupType
from template.domain.models.member import Member
from template.domain.models.split import EqualSplit, ExactAmountsSplit, PercentageSplit
from template.domain.schemas.search import ExpenseSearchResponse, ExpenseSearchResult
from template.service_layer.search_query import parse_query

MAX_RESULTS = 50

logger = logging.getLogger(__name__)


class NotAMemberError(Exception):
    """The member asked to search a group they do not belong to."""


class SearchService:
    def __init__(self, groups: GroupRepository, search: SearchRepository):
        self._groups = groups
        self._search = search

    def search(self, member: Member, q: str, group_id: Optional[int] = None) -> ExpenseSearchResponse:
        """Search `q` across every group the member is in, or just `group_id` when given."""
        query = parse_query(q)
        if query is None:
            return ExpenseSearchResponse(results=[], has_more=False)

        group_ids = self._resolve_group_ids(member, group_id)
        purchase_limit = MAX_RESULTS + 1

        expense_results = self._search_expenses(member, group_ids, query, purchase_limit)
        fixed_results = self._search_fixed(member, group_ids, query, purchase_limit)

        purchases = self._group_into_purchases(expense_results, fixed_results)
        purchases.sort(key=self._purchase_sort_key, reverse=True)
        has_more = len(purchases) > MAX_RESULTS

        results = [row for purchase in purchases[:MAX_RESULTS] for row in purchase]
        results.sort(key=self._sort_key, reverse=True)
        return ExpenseSearchResponse(results=results, has_more=has_more)

    def _resolve_group_ids(self, member: Member, group_id: Optional[int]) -> list[int]:
        """Groups to search: just `group_id` (validated) when given, else every group `member` is in."""
        if group_id is None:
            return self._groups.list_ids_for_member_all(member.id)

        personal = self._groups.get_personal_for_owner(member.id)
        is_own_personal = personal is not None and personal.id == group_id
        if not is_own_personal:
            if self._groups.get(group_id) is None or not self._groups.is_member(group_id, member.id):
                raise NotAMemberError()
        return [group_id]

    def _search_expenses(
        self, member: Member, group_ids: list[int], query, purchase_limit: int
    ) -> list[ExpenseSearchResult]:
        """Expense rows across `group_ids`, each carrying `yourShare` for `member`."""
        members_by_group: dict[int, dict[int, Member]] = {}
        results = []
        for expense, share, group, payer in self._search.search_expenses(group_ids, query, purchase_limit):
            if group.id not in members_by_group:
                members_by_group[group.id] = {m.id: m for m in self._groups.list_members(group.id)}
            results.append(self._from_expense(expense, share, group, payer, member, members_by_group[group.id]))
        return results

    def _search_fixed(
        self, member: Member, group_ids: list[int], query, purchase_limit: int
    ) -> list[ExpenseSearchResult]:
        """Personal fixed-expense months, only when `member`'s own personal group is in scope."""
        personal = self._groups.get_personal_for_owner(member.id)
        if personal is None or personal.id not in group_ids:
            return []
        fixed = self._search.search_personal_fixed(personal.id, member.name, query, purchase_limit)
        return [self._from_fixed(row, personal.id, personal.name, member) for row in fixed]

    @staticmethod
    def _group_into_purchases(
        expense_results: list[ExpenseSearchResult], fixed_results: list[ExpenseSearchResult]
    ) -> list[list[ExpenseSearchResult]]:
        """Group rows into purchases: expense installments share `parentExpenseId`, each
        personal fixed-expense row is its own purchase."""
        by_key: dict[tuple, list[ExpenseSearchResult]] = {}
        for result in expense_results:
            by_key.setdefault(("expense", result.parent_expense_id), []).append(result)
        purchases = list(by_key.values())
        purchases += [[result] for result in fixed_results]
        return purchases

    @classmethod
    def _purchase_sort_key(cls, purchase: list[ExpenseSearchResult]) -> tuple:
        rows_key = [cls._sort_key(r) for r in purchase]
        return (min(d for d, _ in rows_key), max(i for _, i in rows_key))

    @staticmethod
    def _sort_key(result: ExpenseSearchResult) -> tuple:
        day = result.date or date(result.period_year, result.period_month, 1)
        return (day, result.id)

    @staticmethod
    def _deserialize_split_strategy(data: dict):
        """Convert the raw split_strategy JSON column back into a domain SplitStrategy."""
        if data["type"] == "equal":
            return EqualSplit(participant_ids=data.get("participant_ids"))
        if data["type"] == "percentage":
            return PercentageSplit(data["percentages"])
        if data["type"] == "exact":
            return ExactAmountsSplit(data["amounts"])
        raise ValueError(f"Unknown split strategy type: {data['type']}")

    @classmethod
    def _your_share(cls, expense, searcher: Member, group_members: dict[int, Member]) -> Optional[float]:
        """`searcher`'s part of `expense`, or None when today's membership cannot split it
        (e.g. an equal split whose participants have all left the group)."""
        try:
            strategy = cls._deserialize_split_strategy(expense.split_strategy)
            shares = strategy.calculate_shares(expense.amount, list(group_members.values()))
        except ValueError:
            logger.warning("Cannot compute yourShare for expense %s", expense.id, exc_info=True)
            return None
        return shares.get(searcher.id, 0.0)

    @classmethod
    def _from_expense(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls, expense, share, group, payer, searcher: Member, group_members: dict[int, Member]
    ) -> ExpenseSearchResult:
        is_personal = group.group_type == GroupType.PERSONAL.value
        return ExpenseSearchResult(
            kind="expense",
            id=expense.id,
            parent_expense_id=expense.parent_expense_id or expense.id,
            description=expense.description,
            amount=expense.amount,
            currency=expense.currency or "ARS",
            your_share=None if is_personal else cls._your_share(expense, searcher, group_members),
            date=expense.date,
            category=expense.category,
            group_id=group.id,
            group_name=group.name,
            group_type=group.group_type,
            payer_id=payer.id,
            payer_name=payer.name,
            installment_no=expense.installment_no or 1,
            installments=expense.installments or 1,
            period_year=share.year,
            period_month=share.month,
            period_settled=None if is_personal else bool(share.is_settled),
        )

    @staticmethod
    def _from_fixed(row, group_id: int, group_name: str, owner: Member) -> ExpenseSearchResult:
        return ExpenseSearchResult(
            kind="recurring_personal",
            id=row.id,
            parent_expense_id=None,
            description=row.label,
            amount=row.amount,
            currency=row.currency or "ARS",
            your_share=None,
            date=None,
            category=row.category_name,
            group_id=group_id,
            group_name=group_name,
            group_type=GroupType.PERSONAL.value,
            payer_id=owner.id,
            payer_name=owner.name,
            installment_no=1,
            installments=1,
            period_year=row.year,
            period_month=row.month,
            period_settled=None,
        )
