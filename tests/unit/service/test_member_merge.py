"""Absorbing a ghost member into an existing account — in-memory SQLite.

A merge relabels identity and must change no amounts. These tests pin both halves: every
reference to the ghost moves to the survivor, and the arithmetic is untouched — including in
settled months, whose balances JSON never self-heals because recalculate_balances returns early.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import (
    Base,
    ExpenseModel,
    GroupMembershipModel,
    GroupModel,
    MemberModel,
    MonthlyShareModel,
    RecurringGroupExpenseModel,
)
from template.domain.models.enums import PaymentType
from template.domain.models.group import GroupStatus, GroupType
from template.service_layer.member_merge_service import MemberMergeService

GROUP_ID = 1
SURVIVOR_ID = 10
GHOST_ID = 20
OTHER_ID = 30


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    """A group with a full-account survivor, a ghost, and a third full member."""
    session.add_all(
        [
            GroupModel(id=GROUP_ID, name="Asado", status=GroupStatus.ACTIVE, group_type=GroupType.REGULAR),
            MemberModel(id=SURVIVOR_ID, name="Fran", email="fran@example.com", hashed_password="h"),
            MemberModel(id=GHOST_ID, name="Guada", email=None, telephone=None, hashed_password=None),
            MemberModel(id=OTHER_ID, name="Ivi", email="ivi@example.com", hashed_password="h"),
        ]
    )
    session.commit()
    for member_id in (SURVIVOR_ID, GHOST_ID, OTHER_ID):
        session.add(GroupMembershipModel(group_id=GROUP_ID, member_id=member_id))
    session.commit()
    return session


def _add_share(session, *, year=2026, month=5, is_settled=False, balances=None) -> int:
    share = MonthlyShareModel(group_id=GROUP_ID, year=year, month=month, is_settled=is_settled, balances=balances or {})
    session.add(share)
    session.commit()
    return share.id


def _add_expense(session, share_id: int, *, payer_id: int, strategy: dict, amount=100.0) -> int:
    expense = ExpenseModel(
        description="Asado",
        amount=amount,
        date=date(2026, 5, 10),
        category="comida",
        payer_id=payer_id,
        payment_type=PaymentType.DEBIT,
        installments=1,
        installment_no=1,
        split_strategy=strategy,
        monthly_share_id=share_id,
        group_id=GROUP_ID,
    )
    session.add(expense)
    session.commit()
    return expense.id


def _merge(session):
    MemberMergeService(session).merge(GHOST_ID, SURVIVOR_ID, GROUP_ID)


# ---------------------------------------------------------------------------
# FK repointing
# ---------------------------------------------------------------------------


def test_merge_repoints_expense_payer(populated_session):
    """An expense the ghost paid becomes an expense the survivor paid."""
    share = _add_share(populated_session)
    expense_id = _add_expense(populated_session, share, payer_id=GHOST_ID, strategy={"type": "equal"})

    _merge(populated_session)

    assert populated_session.get(ExpenseModel, expense_id).payer_id == SURVIVOR_ID


def test_merge_repoints_recurring_group_expense(populated_session):
    """Templates carry their own payer_id and split_strategy, separate from the rows they make."""
    template = RecurringGroupExpenseModel(
        group_id=GROUP_ID,
        description="Internet",
        amount=500.0,
        category="servicios",
        payer_id=GHOST_ID,
        payment_type=PaymentType.DEBIT,
        split_strategy={"type": "equal", "participant_ids": [GHOST_ID, OTHER_ID]},
        start_year=2026,
        start_month=5,
    )
    populated_session.add(template)
    populated_session.commit()

    _merge(populated_session)

    refreshed = populated_session.get(RecurringGroupExpenseModel, template.id)
    assert refreshed.payer_id == SURVIVOR_ID
    assert sorted(refreshed.split_strategy["participant_ids"]) == sorted([SURVIVOR_ID, OTHER_ID])


# ---------------------------------------------------------------------------
# split_strategy JSON
# ---------------------------------------------------------------------------


def test_merge_rewrites_participant_ids(populated_session):
    """EqualSplit participant_ids entries are remapped."""
    share = _add_share(populated_session)
    expense_id = _add_expense(
        populated_session,
        share,
        payer_id=OTHER_ID,
        strategy={"type": "equal", "participant_ids": [GHOST_ID, OTHER_ID]},
    )

    _merge(populated_session)

    strategy = populated_session.get(ExpenseModel, expense_id).split_strategy
    assert sorted(strategy["participant_ids"]) == sorted([SURVIVOR_ID, OTHER_ID])


def test_merge_does_not_duplicate_a_participant_already_present(populated_session):
    """If both ids participate, the survivor appears once — not twice."""
    share = _add_share(populated_session)
    expense_id = _add_expense(
        populated_session,
        share,
        payer_id=OTHER_ID,
        strategy={"type": "equal", "participant_ids": [GHOST_ID, SURVIVOR_ID, OTHER_ID]},
    )

    _merge(populated_session)

    ids = populated_session.get(ExpenseModel, expense_id).split_strategy["participant_ids"]
    assert sorted(ids) == sorted([SURVIVOR_ID, OTHER_ID])
    assert ids.count(SURVIVOR_ID) == 1


def test_merge_rewrites_percentage_keys_without_touching_values(populated_session):
    """percentages is keyed by member id: the key moves, the number does not."""
    share = _add_share(populated_session)
    expense_id = _add_expense(
        populated_session,
        share,
        payer_id=OTHER_ID,
        strategy={"type": "percentage", "percentages": {str(GHOST_ID): 40.0, str(OTHER_ID): 60.0}},
    )

    _merge(populated_session)

    percentages = populated_session.get(ExpenseModel, expense_id).split_strategy["percentages"]
    assert percentages == {str(SURVIVOR_ID): 40.0, str(OTHER_ID): 60.0}


def test_merge_adds_shares_when_both_ids_appear_in_one_split(populated_session):
    """Ghost and survivor in the same split collapse to one entry holding both shares.

    Anything else would change the expense total.
    """
    share = _add_share(populated_session)
    expense_id = _add_expense(
        populated_session,
        share,
        payer_id=OTHER_ID,
        strategy={
            "type": "exact",
            "amounts": {str(GHOST_ID): 30.0, str(SURVIVOR_ID): 20.0, str(OTHER_ID): 50.0},
        },
    )

    _merge(populated_session)

    amounts = populated_session.get(ExpenseModel, expense_id).split_strategy["amounts"]
    assert amounts == {str(SURVIVOR_ID): 50.0, str(OTHER_ID): 50.0}
    assert sum(amounts.values()) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# balances JSON, including settled months
# ---------------------------------------------------------------------------


def test_merge_rewrites_balances_in_a_settled_month(populated_session):
    """recalculate_balances returns early when settled, so the keys must be remapped here."""
    share_id = _add_share(
        populated_session,
        is_settled=True,
        balances={str(GHOST_ID): -50.0, str(OTHER_ID): 50.0},
    )

    _merge(populated_session)

    balances = populated_session.get(MonthlyShareModel, share_id).balances
    assert balances == {str(SURVIVOR_ID): -50.0, str(OTHER_ID): 50.0}


def test_merge_preserves_the_balance_total(populated_session):
    """The invariant that proves no money moved."""
    share_id = _add_share(
        populated_session,
        is_settled=True,
        balances={str(GHOST_ID): -30.0, str(SURVIVOR_ID): -20.0, str(OTHER_ID): 50.0},
    )
    before = sum(populated_session.get(MonthlyShareModel, share_id).balances.values())

    _merge(populated_session)

    after = sum(populated_session.get(MonthlyShareModel, share_id).balances.values())
    assert after == pytest.approx(before)
    assert populated_session.get(MonthlyShareModel, share_id).balances[str(SURVIVOR_ID)] == pytest.approx(-50.0)


# ---------------------------------------------------------------------------
# Membership, preconditions, cleanup
# ---------------------------------------------------------------------------


def test_merge_collapses_duplicate_membership(populated_session):
    """Both rows are already in the group — one membership survives, no constraint violation."""
    _merge(populated_session)

    rows = (
        populated_session.query(GroupMembershipModel)
        .filter(GroupMembershipModel.group_id == GROUP_ID, GroupMembershipModel.member_id == SURVIVOR_ID)
        .all()
    )
    assert len(rows) == 1


def test_merge_moves_membership_when_the_survivor_was_not_in_the_group(populated_session):
    """Claiming a ghost in a group you are not yet in puts you in it."""
    populated_session.query(GroupMembershipModel).filter(GroupMembershipModel.member_id == SURVIVOR_ID).delete()
    populated_session.commit()

    _merge(populated_session)

    memberships = (
        populated_session.query(GroupMembershipModel)
        .filter(GroupMembershipModel.group_id == GROUP_ID, GroupMembershipModel.member_id == SURVIVOR_ID)
        .count()
    )
    assert memberships == 1


def test_merge_deletes_the_ghost(populated_session):
    """The absorbed row is gone, so it can never be claimed twice."""
    _merge(populated_session)

    assert populated_session.get(MemberModel, GHOST_ID) is None


@pytest.mark.parametrize(
    "field,value",
    [("email", "guada@example.com"), ("telephone", "5411999999"), ("hashed_password", "hashed")],
)
def test_merge_rejects_a_member_that_is_not_a_ghost(populated_session, field, value):
    """Only a contactless stub may be absorbed — an invited stub or a real account may not."""
    ghost = populated_session.get(MemberModel, GHOST_ID)
    setattr(ghost, field, value)
    populated_session.commit()

    with pytest.raises(ValueError):
        _merge(populated_session)

    assert populated_session.get(MemberModel, GHOST_ID) is not None


def test_merge_rejects_merging_a_member_into_itself(populated_session):
    """Guards against a caller passing the same id twice."""
    with pytest.raises(ValueError):
        MemberMergeService(populated_session).merge(SURVIVOR_ID, SURVIVOR_ID, GROUP_ID)
