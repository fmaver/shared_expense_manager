"""Expense search for one member: every group they are in, or one of them."""

from datetime import date
from typing import Optional

from template.adapters.repositories import GroupRepository, SearchRepository
from template.domain.models.group import GroupType
from template.domain.models.member import Member
from template.domain.schemas.search import ExpenseSearchResponse, ExpenseSearchResult
from template.service_layer.search_query import parse_query

MAX_RESULTS = 50


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

        if group_id is not None:
            if not self._groups.is_member(group_id, member.id):
                personal = self._groups.get_personal_for_owner(member.id)
                if personal is None or personal.id != group_id:
                    raise NotAMemberError()
            group_ids = [group_id]
        else:
            group_ids = self._groups.list_ids_for_member_all(member.id)

        fetch = MAX_RESULTS + 1
        results = [self._from_expense(*row) for row in self._search.search_expenses(group_ids, query, fetch)]

        personal = self._groups.get_personal_for_owner(member.id)
        if personal is not None and personal.id in group_ids:
            fixed = self._search.search_personal_fixed(personal.id, member.name, query, fetch)
            results += [self._from_fixed(row, personal.id, personal.name, member) for row in fixed]

        results.sort(key=self._sort_key, reverse=True)
        return ExpenseSearchResponse(results=results[:MAX_RESULTS], has_more=len(results) > MAX_RESULTS)

    @staticmethod
    def _sort_key(result: ExpenseSearchResult) -> tuple:
        day = result.date or date(result.period_year, result.period_month, 1)
        return (day, result.id)

    @staticmethod
    def _from_expense(expense, share, group, payer) -> ExpenseSearchResult:
        is_personal = group.group_type == GroupType.PERSONAL.value
        return ExpenseSearchResult(
            kind="expense",
            id=expense.id,
            description=expense.description,
            amount=expense.amount,
            currency=expense.currency or "ARS",
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
            description=row.label,
            amount=row.amount,
            currency=row.currency or "ARS",
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
