"""Archiving a group — in-memory SQLite.

Archiving lives on the *membership*, not the group: you archive it for yourself and everyone
else keeps using it unchanged. That property is what most of these tests exist to protect.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupMembershipModel, MemberModel
from template.adapters.repositories import GroupRepository, SQLAlchemyExpenseRepository
from template.domain.models.enums import PaymentType
from template.domain.models.group import GroupType
from template.domain.schemas.expense import ExpenseCreate, SplitStrategySchema
from template.service_layer.expense_service import ExpenseService
from template.service_layer.group_service import GroupService

OWNER_ID = 1
OTHER_ID = 2


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    session.add_all(
        [
            MemberModel(id=OWNER_ID, name="Fran", email="fran@example.com", hashed_password="h"),
            MemberModel(id=OTHER_ID, name="Guada", email="guada@example.com", hashed_password="h"),
        ]
    )
    session.commit()
    return session


def _group(session, name="Casa") -> int:
    group = GroupService(GroupRepository(session)).create(name, OWNER_ID)
    session.add(GroupMembershipModel(group_id=group.id, member_id=OTHER_ID))
    session.commit()
    return group.id


def _service(session) -> GroupService:
    return GroupService(GroupRepository(session))


def _expense_service(session, group_id: int) -> ExpenseService:
    return ExpenseService(SQLAlchemyExpenseRepository(session), group_id, GroupRepository(session))


def _add_expense(session, group_id: int, payer_id: int, amount: float = 100.0):
    return _expense_service(session, group_id).create_expense(
        ExpenseCreate(
            description="Luz",
            amount=amount,
            date=date(2026, 5, 10),
            category={"name": "servicios"},
            payer_id=payer_id,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal", participant_ids=None),
        )
    )


def _group_ids(groups) -> list:
    return [g.id for g in groups]


# ---------------------------------------------------------------------------
# The column
# ---------------------------------------------------------------------------


def test_a_new_membership_is_not_archived(populated_session):
    """Existing rows must read as not archived, so the migration needs no backfill."""
    group_id = _group(populated_session)

    row = (
        populated_session.query(GroupMembershipModel)
        .filter(GroupMembershipModel.group_id == group_id, GroupMembershipModel.member_id == OWNER_ID)
        .one()
    )
    assert row.archived_at is None


# ---------------------------------------------------------------------------
# Per-member visibility
# ---------------------------------------------------------------------------


def test_archiving_hides_the_group_from_my_list(populated_session):
    service = _service(populated_session)
    group_id = _group(populated_session)

    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    assert group_id not in _group_ids(service.list_for_member(OWNER_ID))


def test_archiving_shows_it_in_my_archived_list(populated_session):
    service = _service(populated_session)
    group_id = _group(populated_session)

    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    assert group_id in _group_ids(service.list_archived_for_member(OWNER_ID))


def test_archiving_does_not_affect_anyone_else(populated_session):
    """The property the whole design rests on."""
    service = _service(populated_session)
    group_id = _group(populated_session)

    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    assert group_id in _group_ids(service.list_for_member(OTHER_ID))
    assert group_id not in _group_ids(service.list_archived_for_member(OTHER_ID))


def test_unarchiving_brings_it_back(populated_session):
    service = _service(populated_session)
    group_id = _group(populated_session)
    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    service.unarchive(group_id, OWNER_ID)

    assert group_id in _group_ids(service.list_for_member(OWNER_ID))
    assert group_id not in _group_ids(service.list_archived_for_member(OWNER_ID))


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def test_cannot_archive_with_an_outstanding_balance(populated_session):
    """Same rule as leaving: settle before you put it away."""
    service = _service(populated_session)
    group_id = _group(populated_session)

    with pytest.raises(ValueError):
        service.archive(group_id, OWNER_ID, outstanding_balance=50.0)

    assert group_id in _group_ids(service.list_for_member(OWNER_ID))


def test_cannot_archive_a_personal_group(populated_session):
    """A personal group is the member's own ledger and has nowhere to go."""
    service = _service(populated_session)
    personal = service.get_or_create_personal_group(OWNER_ID)

    with pytest.raises(ValueError):
        service.archive(personal.id, OWNER_ID, outstanding_balance=0.0)


# ---------------------------------------------------------------------------
# Auto-unarchive
# ---------------------------------------------------------------------------


def test_an_expense_that_affects_me_brings_the_group_back(populated_session):
    """Silence is only safe if debt cannot pile up behind an archived group."""
    service = _service(populated_session)
    group_id = _group(populated_session)
    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    # The other member pays; an equal split leaves the archiver owing half.
    _add_expense(populated_session, group_id, payer_id=OTHER_ID)
    service.refresh_archived_state(group_id, SQLAlchemyExpenseRepository(populated_session))

    assert group_id in _group_ids(service.list_for_member(OWNER_ID))


def test_an_expense_that_does_not_affect_me_leaves_it_archived(populated_session):
    """Only my own balance decides whether the group is relevant to me again."""
    service = _service(populated_session)
    group_id = _group(populated_session)
    service.archive(group_id, OWNER_ID, outstanding_balance=0.0)

    # Split restricted to the other member, so the archiver's balance stays at zero.
    _expense_service(populated_session, group_id).create_expense(
        ExpenseCreate(
            description="Solo suyo",
            amount=100.0,
            date=date(2026, 5, 10),
            category={"name": "servicios"},
            payer_id=OTHER_ID,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal", participant_ids=[OTHER_ID]),
        )
    )
    service.refresh_archived_state(group_id, SQLAlchemyExpenseRepository(populated_session))

    assert group_id not in _group_ids(service.list_for_member(OWNER_ID))
    assert group_id in _group_ids(service.list_archived_for_member(OWNER_ID))
