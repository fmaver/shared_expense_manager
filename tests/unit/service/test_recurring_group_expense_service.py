"""Unit tests for materialize_recurring_group_expenses service function."""

from unittest.mock import MagicMock, call

import pytest

from template.domain.schemas.expense import SplitStrategySchema
from template.service_layer.recurring_group_expense_service import materialize_recurring_group_expenses


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(
    template_id: int = 1,
    start_year: int = 2026,
    start_month: int = 5,
    group_id: int = 1,
    description: str = "Internet",
    amount: float = 500.0,
    category: str = "servicios",
    payer_id: int = 1,
    payment_type: str = "debit",
    split_strategy: SplitStrategySchema | None = None,
) -> MagicMock:
    """Build a mock recurring group expense template.

    Note: split_strategy must be a SplitStrategySchema (not a plain dict) because
    materialize_recurring_group_expenses passes it directly to _build_split_strategy
    which calls schema.type as an attribute.
    """
    t = MagicMock()
    t.id = template_id
    t.start_year = start_year
    t.start_month = start_month
    t.group_id = group_id
    t.description = description
    t.amount = amount
    t.category = category
    t.payer_id = payer_id
    t.payment_type = payment_type
    # participant_ids=None → EqualSplit for all members (the standard DB-deserialized form)
    t.split_strategy = split_strategy or SplitStrategySchema(type="equal", participant_ids=None)
    return t


def _make_settled_share() -> MagicMock:
    share = MagicMock()
    share.is_settled = True
    return share


def _make_unsettled_share() -> MagicMock:
    share = MagicMock()
    share.is_settled = False
    return share


def _build_deps(
    templates=None,
    monthly_share=None,
    upsert_returns: bool = True,
):
    """Build mocked dependencies for materialize_recurring_group_expenses."""
    recurring_repo = MagicMock()
    recurring_repo.list_for_group.return_value = templates if templates is not None else []
    recurring_repo.upsert_instance.return_value = upsert_returns

    expense_repo = MagicMock()

    expense_manager = MagicMock()
    expense_manager.get_monthly_balance.return_value = monthly_share

    return recurring_repo, expense_repo, expense_manager


# ---------------------------------------------------------------------------
# Test 1: Skips settled month entirely
# ---------------------------------------------------------------------------


def test_materialize_skips_settled_month():
    """If the month is already settled, no instances are created and no expenses are materialized."""
    settled = _make_settled_share()
    recurring_repo, expense_repo, expense_manager = _build_deps(
        templates=[_make_template()],
        monthly_share=settled,
    )

    materialize_recurring_group_expenses(
        group_id=1,
        year=2026,
        month=5,
        recurring_repo=recurring_repo,
        expense_repo=expense_repo,
        expense_manager=expense_manager,
    )

    # Should not even list templates or create anything
    recurring_repo.list_for_group.assert_not_called()
    recurring_repo.upsert_instance.assert_not_called()
    expense_manager._add_to_monthly_share.assert_not_called()  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Test 2: Skips future templates
# ---------------------------------------------------------------------------


def test_materialize_skips_future_templates():
    """Templates with start_year/start_month after the viewed period are skipped."""
    # Template starts in July 2026, but we're viewing May 2026
    future_template = _make_template(start_year=2026, start_month=7)
    recurring_repo, expense_repo, expense_manager = _build_deps(
        templates=[future_template],
        monthly_share=None,  # no share → unsettled by definition
    )

    materialize_recurring_group_expenses(
        group_id=1,
        year=2026,
        month=5,
        recurring_repo=recurring_repo,
        expense_repo=expense_repo,
        expense_manager=expense_manager,
    )

    recurring_repo.upsert_instance.assert_not_called()
    expense_manager._add_to_monthly_share.assert_not_called()  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Test 3: Creates expense when upsert returns True (new instance)
# ---------------------------------------------------------------------------


def test_materialize_creates_expense_for_new_instance():
    """When upsert_instance returns True (new record), an expense is created and tagged."""
    template = _make_template(template_id=42, start_year=2026, start_month=5)

    # set_recurring_template_id must be callable; expense_manager._add_to_monthly_share
    # must set expense.id so the tag call happens.
    def _fake_add_to_monthly_share(expense, expense_date):  # pylint: disable=unused-argument
        expense.id = 99

    recurring_repo, expense_repo, expense_manager = _build_deps(
        templates=[template],
        monthly_share=None,
        upsert_returns=True,
    )
    expense_manager._add_to_monthly_share.side_effect = _fake_add_to_monthly_share  # pylint: disable=protected-access

    materialize_recurring_group_expenses(
        group_id=1,
        year=2026,
        month=5,
        recurring_repo=recurring_repo,
        expense_repo=expense_repo,
        expense_manager=expense_manager,
    )

    recurring_repo.upsert_instance.assert_called_once_with(42, 1, 2026, 5)
    expense_manager._add_to_monthly_share.assert_called_once()  # pylint: disable=protected-access
    expense_repo.set_recurring_template_id.assert_called_once_with(99, 42)


# ---------------------------------------------------------------------------
# Test 4: Skips already-materialized instances
# ---------------------------------------------------------------------------


def test_materialize_skips_already_materialized():
    """When upsert_instance returns False (already exists), no expense is created."""
    template = _make_template(template_id=7)
    recurring_repo, expense_repo, expense_manager = _build_deps(
        templates=[template],
        monthly_share=None,
        upsert_returns=False,  # already exists
    )

    materialize_recurring_group_expenses(
        group_id=1,
        year=2026,
        month=5,
        recurring_repo=recurring_repo,
        expense_repo=expense_repo,
        expense_manager=expense_manager,
    )

    recurring_repo.upsert_instance.assert_called_once()
    expense_manager._add_to_monthly_share.assert_not_called()  # pylint: disable=protected-access
    expense_repo.set_recurring_template_id.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: Empty template list — no error
# ---------------------------------------------------------------------------


def test_materialize_handles_empty_template_list():
    """When there are no templates, the function returns without error."""
    recurring_repo, expense_repo, expense_manager = _build_deps(
        templates=[],
        monthly_share=None,
    )

    # Must not raise
    materialize_recurring_group_expenses(
        group_id=1,
        year=2026,
        month=5,
        recurring_repo=recurring_repo,
        expense_repo=expense_repo,
        expense_manager=expense_manager,
    )

    recurring_repo.list_for_group.assert_called_once_with(1, active_only=True)
    expense_manager._add_to_monthly_share.assert_not_called()  # pylint: disable=protected-access
