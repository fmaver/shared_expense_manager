"""Unit tests for PersonalLedgerService."""

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from template.domain.models.category import Category
from template.domain.models.group import Group, GroupStatus, GroupType
from template.domain.models.income import IncomeInstance
from template.service_layer.personal_ledger_service import PersonalLedgerService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_personal_group(group_id=99):
    return Group(
        id=group_id,
        name="Personal",
        status=GroupStatus.ACTIVE,
        group_type=GroupType.PERSONAL,
        owner_member_id=1,
    )


def _make_regular_group(group_id=1):
    return Group(id=group_id, name="Shared", status=GroupStatus.ACTIVE, group_type=GroupType.REGULAR)


def _make_income_instance(amount: float, group_id: int = 99, member_id: int = 1) -> IncomeInstance:
    return IncomeInstance(
        id=1,
        personal_group_id=group_id,
        owner_member_id=member_id,
        year=2025,
        month=6,
        source="recurring",
        label="Sueldo",
        amount=amount,
    )


def _make_mock_expense(
    expense_id,
    amount,
    payer_id,
    category_name,
    owner_share=None,
    all_member_ids=None,
):
    """Build a mock Expense with a mock split strategy."""
    mock_expense = MagicMock()
    mock_expense.id = expense_id
    mock_expense.description = f"Expense {expense_id}"
    mock_expense.amount = amount
    mock_expense.payer_id = payer_id
    mock_expense.date = date(2025, 6, 15)
    mock_expense.category = MagicMock()
    mock_expense.category.name = category_name
    mock_expense.payment_type = "debit"
    mock_expense.installments = 1
    mock_expense.installment_no = 1
    mock_expense.parent_expense_id = None

    if owner_share is not None and all_member_ids is not None:
        shares_dict = {mid: (owner_share if mid == 1 else amount - owner_share) for mid in all_member_ids}
        mock_expense.split_strategy = MagicMock()
        mock_expense.split_strategy.calculate_shares.return_value = shares_dict
    return mock_expense


def _build_service(
    personal_group=None,
    other_groups=None,
    income_instances=None,
    personal_share=None,
    other_shares=None,  # dict: group_id → share or None
    members_per_group=None,  # dict: group_id → list of member mocks
):
    """Create a PersonalLedgerService with all deps mocked."""
    if personal_group is None:
        personal_group = _make_personal_group()
    if other_groups is None:
        other_groups = []
    if income_instances is None:
        income_instances = []
    if other_shares is None:
        other_shares = {}
    if members_per_group is None:
        members_per_group = {}

    group_service = MagicMock()
    group_service.get_or_create_personal_group.return_value = personal_group

    group_repo = MagicMock()
    group_repo.list_for_member.return_value = other_groups

    def _list_members(gid):
        members = members_per_group.get(gid, [])
        return members

    group_repo.list_members.side_effect = _list_members

    expense_repo = MagicMock()
    expense_repo.get_monthly_share.side_effect = lambda year, month, group_id: (
        personal_share if group_id == personal_group.id else other_shares.get(group_id)
    )

    income_repo = MagicMock()
    income_repo.list_instances_for_month.return_value = income_instances
    income_repo.list_recurring.return_value = []  # no recurring templates by default

    svc = PersonalLedgerService(
        group_service=group_service,
        group_repo=group_repo,
        expense_repo=expense_repo,
        income_repo=income_repo,
    )
    return svc, group_service, group_repo, expense_repo, income_repo


# ---------------------------------------------------------------------------
# Test 1: Empty ledger
# ---------------------------------------------------------------------------


def test_empty_ledger_all_zeros():
    """No income, no expenses, no other groups → all zeros, no mirrored shares."""
    svc, *_ = _build_service()
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert ledger.total_income == 0.0
    assert ledger.total_personal_expenses == 0.0
    assert ledger.total_shares_pending == 0.0
    assert ledger.total_shares_realized == 0.0
    assert ledger.projected_balance == 0.0
    assert ledger.realized_balance == 0.0
    assert ledger.pending_settlements_total == 0.0
    assert ledger.mirrored_shares == []


# ---------------------------------------------------------------------------
# Test 2: Income appears
# ---------------------------------------------------------------------------


def test_income_appears_in_ledger():
    """One recurring income instance → total_income populated, projected_balance positive."""
    instance = _make_income_instance(amount=1500.0)
    svc, *_ = _build_service(income_instances=[instance])
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert ledger.total_income == 1500.0
    assert ledger.projected_balance == 1500.0
    assert len(ledger.incomes) == 1
    assert ledger.incomes[0].amount == 1500.0


# ---------------------------------------------------------------------------
# Test 3: Mirrored share pending
# ---------------------------------------------------------------------------


def test_mirrored_share_pending():
    """Owner in a 2-member shared group, expense $200 split equally, month unsettled → pending."""
    shared_group = _make_regular_group(group_id=2)
    expense = _make_mock_expense(
        expense_id=10,
        amount=200.0,
        payer_id=2,
        category_name="salidas",
        owner_share=100.0,
        all_member_ids=[1, 2],
    )
    mock_share = MagicMock()
    mock_share.expenses = [expense]
    mock_share.is_settled = False

    # Build member mocks
    owner_member = MagicMock()
    owner_member.id = 1
    other_member = MagicMock()
    other_member.id = 2

    svc, *_ = _build_service(
        other_groups=[shared_group],
        other_shares={2: mock_share},
        members_per_group={2: [owner_member, other_member]},
    )
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert len(ledger.mirrored_shares) == 1
    item = ledger.mirrored_shares[0]
    assert item.share_amount == 100.0
    assert item.status == "pending"
    assert item.source_group_id == 2
    assert ledger.total_shares_pending == 100.0
    assert ledger.total_shares_realized == 0.0
    assert ledger.projected_balance == -100.0


# ---------------------------------------------------------------------------
# Test 4: Mirrored share realized
# ---------------------------------------------------------------------------


def test_mirrored_share_realized():
    """Same but source month is_settled=True → status=='realized', realized_balance decreases."""
    shared_group = _make_regular_group(group_id=2)
    expense = _make_mock_expense(
        expense_id=10,
        amount=200.0,
        payer_id=2,
        category_name="salidas",
        owner_share=100.0,
        all_member_ids=[1, 2],
    )
    mock_share = MagicMock()
    mock_share.expenses = [expense]
    mock_share.is_settled = True

    owner_member = MagicMock()
    owner_member.id = 1
    other_member = MagicMock()
    other_member.id = 2

    svc, *_ = _build_service(
        other_groups=[shared_group],
        other_shares={2: mock_share},
        members_per_group={2: [owner_member, other_member]},
    )
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert len(ledger.mirrored_shares) == 1
    item = ledger.mirrored_shares[0]
    assert item.share_amount == 100.0
    assert item.status == "realized"
    assert ledger.total_shares_pending == 0.0
    assert ledger.total_shares_realized == 100.0
    assert ledger.realized_balance == -100.0


# ---------------------------------------------------------------------------
# Test 5: Owner's payer status irrelevant
# ---------------------------------------------------------------------------


def test_owner_payer_status_irrelevant():
    """Owner paid the $200 (payer_id=owner), share still = 100.0 (accrual)."""
    shared_group = _make_regular_group(group_id=2)
    # payer_id=1 (owner pays), but share is still 100
    expense = _make_mock_expense(
        expense_id=10,
        amount=200.0,
        payer_id=1,
        category_name="supermercado",
        owner_share=100.0,
        all_member_ids=[1, 2],
    )
    mock_share = MagicMock()
    mock_share.expenses = [expense]
    mock_share.is_settled = False

    owner_member = MagicMock()
    owner_member.id = 1
    other_member = MagicMock()
    other_member.id = 2

    svc, *_ = _build_service(
        other_groups=[shared_group],
        other_shares={2: mock_share},
        members_per_group={2: [owner_member, other_member]},
    )
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert len(ledger.mirrored_shares) == 1
    assert ledger.mirrored_shares[0].share_amount == 100.0


# ---------------------------------------------------------------------------
# Test 6: Internal categories excluded
# ---------------------------------------------------------------------------


def test_internal_categories_excluded():
    """Expense with category 'balance' → NOT in mirrored shares."""
    shared_group = _make_regular_group(group_id=2)
    expense = _make_mock_expense(
        expense_id=10,
        amount=200.0,
        payer_id=2,
        category_name="balance",
        owner_share=100.0,
        all_member_ids=[1, 2],
    )
    mock_share = MagicMock()
    mock_share.expenses = [expense]
    mock_share.is_settled = False

    owner_member = MagicMock()
    owner_member.id = 1
    other_member = MagicMock()
    other_member.id = 2

    svc, *_ = _build_service(
        other_groups=[shared_group],
        other_shares={2: mock_share},
        members_per_group={2: [owner_member, other_member]},
    )
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert ledger.mirrored_shares == []
    assert ledger.total_shares_pending == 0.0


# ---------------------------------------------------------------------------
# Test 7: Owner excluded from split
# ---------------------------------------------------------------------------


def test_owner_excluded_from_split():
    """EqualSplit with participant_ids=[2] (NOT owner) → owner_share=0, no mirrored share."""
    shared_group = _make_regular_group(group_id=2)
    expense = _make_mock_expense(
        expense_id=10,
        amount=200.0,
        payer_id=2,
        category_name="salidas",
        owner_share=0.0,
        all_member_ids=[1, 2],
    )
    mock_share = MagicMock()
    mock_share.expenses = [expense]
    mock_share.is_settled = False

    owner_member = MagicMock()
    owner_member.id = 1
    other_member = MagicMock()
    other_member.id = 2

    svc, *_ = _build_service(
        other_groups=[shared_group],
        other_shares={2: mock_share},
        members_per_group={2: [owner_member, other_member]},
    )
    ledger = svc.get_ledger(owner_member_id=1, year=2025, month=6)

    assert ledger.mirrored_shares == []
    assert ledger.total_shares_pending == 0.0


# ---------------------------------------------------------------------------
# Test 8: Materialization called
# ---------------------------------------------------------------------------


def test_materialize_recurring_income_called():
    """_materialize_recurring_income is called with correct args during get_ledger."""
    personal_group = _make_personal_group(group_id=99)
    svc, _, _, _, income_repo = _build_service(personal_group=personal_group)

    # Expose a recurring template so we can verify the upsert call
    mock_template = MagicMock()
    mock_template.id = 5
    mock_template.label = "Sueldo"
    mock_template.amount = 2000.0
    income_repo.list_recurring.return_value = [mock_template]

    svc.get_ledger(owner_member_id=1, year=2025, month=6)

    income_repo.upsert_recurring_instance.assert_called_once_with(
        personal_group_id=99,
        owner_member_id=1,
        year=2025,
        month=6,
        recurring_income_id=5,
        label="Sueldo",
        amount=2000.0,
    )


# ---------------------------------------------------------------------------
# Test 9: get_or_create_personal_group called
# ---------------------------------------------------------------------------


def test_get_or_create_personal_group_called():
    """group_service.get_or_create_personal_group is invoked as the first step."""
    svc, group_service, *_ = _build_service()
    svc.get_ledger(owner_member_id=1, year=2025, month=6)
    group_service.get_or_create_personal_group.assert_called_once_with(1)
