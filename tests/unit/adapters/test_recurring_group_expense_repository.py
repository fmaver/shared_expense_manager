"""Unit tests for RecurringGroupExpenseRepository — in-memory SQLite."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, RecurringGroupExpenseInstanceModel, RecurringGroupExpenseModel
from template.adapters.repositories import RecurringGroupExpenseRepository
from template.domain.models.enums import NotificationType, PaymentType
from template.domain.schemas.expense import RecurringGroupExpenseCreate, SplitStrategySchema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session():
    """Return a fresh in-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    """Session that has one group and one member pre-inserted."""
    from template.adapters.orm import GroupModel, MemberModel

    member = MemberModel(
        name="Fran",
        telephone="5491111111111",
        email="fran@test.com",
        notification_preference=NotificationType.NONE,
    )
    session.add(member)
    session.flush()

    group = GroupModel(name="Test Group")
    session.add(group)
    session.flush()
    session.commit()

    return session, member.id, group.id


def _create_template(repo, group_id: int, payer_id: int, start_year: int = 2026, start_month: int = 5):
    """Helper to create a recurring group expense template via the repo."""
    data = RecurringGroupExpenseCreate(
        description="Netflix",
        amount=200.0,
        category="entretenimiento",
        payer_id=payer_id,
        payment_type=PaymentType.DEBIT,
        # participant_ids=[] is required: _serialize_split_strategy raises for equal+None participant_ids
        split_strategy=SplitStrategySchema(type="equal", participant_ids=[]),
        start_year=start_year,
        start_month=start_month,
    )
    return repo.create(group_id, data)


def _add_instance(session, template_id: int, group_id: int, year: int, month: int):
    """Directly insert an instance record into the DB."""
    instance = RecurringGroupExpenseInstanceModel(
        recurring_expense_id=template_id,
        group_id=group_id,
        year=year,
        month=month,
    )
    session.add(instance)
    session.commit()
    return instance


# ---------------------------------------------------------------------------
# Test 1: delete_instances_from_month_onwards — same year, same/later month
# ---------------------------------------------------------------------------


def test_delete_instances_from_month_onwards_current_year(populated_session):
    """Instances for year==Y and month>=M are deleted; earlier months are kept."""
    session, member_id, group_id = populated_session
    repo = RecurringGroupExpenseRepository(session)
    template = _create_template(repo, group_id, member_id, start_year=2026, start_month=1)

    # Add instances for April, May, June 2026 and January 2027
    _add_instance(session, template.id, group_id, 2026, 4)  # before → keep
    _add_instance(session, template.id, group_id, 2026, 5)  # == month → delete
    _add_instance(session, template.id, group_id, 2026, 6)  # after → delete
    _add_instance(session, template.id, group_id, 2027, 1)  # future year → delete

    # Delete from May 2026 onwards
    repo.delete_instances_from_month_onwards(template.id, year=2026, month=5)

    remaining = (
        session.query(RecurringGroupExpenseInstanceModel)
        .filter(RecurringGroupExpenseInstanceModel.recurring_expense_id == template.id)
        .all()
    )
    remaining_periods = {(r.year, r.month) for r in remaining}

    assert (2026, 4) in remaining_periods, "April 2026 should NOT be deleted"
    assert (2026, 5) not in remaining_periods, "May 2026 should be deleted (month == viewed_month)"
    assert (2026, 6) not in remaining_periods, "June 2026 should be deleted (month > viewed_month)"
    assert (2027, 1) not in remaining_periods, "Jan 2027 should be deleted (year > viewed_year)"


# ---------------------------------------------------------------------------
# Test 2: delete_instances_from_month_onwards — future year (any month deleted)
# ---------------------------------------------------------------------------


def test_delete_instances_from_month_onwards_future_year(populated_session):
    """All instances for year > viewed_year are deleted regardless of month."""
    session, member_id, group_id = populated_session
    repo = RecurringGroupExpenseRepository(session)
    template = _create_template(repo, group_id, member_id)

    _add_instance(session, template.id, group_id, 2026, 5)   # same year, same month → deleted
    _add_instance(session, template.id, group_id, 2027, 1)   # future year, January → deleted
    _add_instance(session, template.id, group_id, 2027, 12)  # future year, December → deleted

    repo.delete_instances_from_month_onwards(template.id, year=2026, month=5)

    count = (
        session.query(RecurringGroupExpenseInstanceModel)
        .filter(RecurringGroupExpenseInstanceModel.recurring_expense_id == template.id)
        .count()
    )
    assert count == 0, "All instances from May 2026 onwards (including future years) should be deleted"


# ---------------------------------------------------------------------------
# Test 3: delete_instances_from_month_onwards — past records are NOT deleted
# ---------------------------------------------------------------------------


def test_delete_instances_from_month_onwards_past_stays(populated_session):
    """Instance records before (year, month) are not affected by the delete."""
    session, member_id, group_id = populated_session
    repo = RecurringGroupExpenseRepository(session)
    template = _create_template(repo, group_id, member_id, start_year=2026, start_month=1)

    # Insert instances spanning multiple months; we'll delete from June 2026 onwards
    past_periods = [(2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]
    future_periods = [(2026, 6), (2026, 7), (2027, 3)]

    for y, m in past_periods + future_periods:
        _add_instance(session, template.id, group_id, y, m)

    repo.delete_instances_from_month_onwards(template.id, year=2026, month=6)

    remaining = (
        session.query(RecurringGroupExpenseInstanceModel)
        .filter(RecurringGroupExpenseInstanceModel.recurring_expense_id == template.id)
        .all()
    )
    remaining_periods = {(r.year, r.month) for r in remaining}

    for period in past_periods:
        assert period in remaining_periods, f"{period} should NOT have been deleted"

    for period in future_periods:
        assert period not in remaining_periods, f"{period} should have been deleted"
