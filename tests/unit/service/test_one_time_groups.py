"""One-time (occasion) groups — in-memory SQLite.

A one-time group is for a trip or a dinner: no months, one balance, one settle. Monthly shares
still exist underneath (so nothing about the schema or the balance math changes), but they are
aggregated away at the edges.
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
from template.service_layer.occasion_service import OccasionService

CREATOR_ID = 1
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
            MemberModel(id=CREATOR_ID, name="Fran", email="fran@example.com", hashed_password="h"),
            MemberModel(id=OTHER_ID, name="Guada", email="guada@example.com", hashed_password="h"),
        ]
    )
    session.commit()
    return session


def _one_time_group(session, name="Viaje a Bariloche") -> int:
    group = GroupService(GroupRepository(session)).create(name, CREATOR_ID, group_type=GroupType.ONE_TIME)
    session.add(GroupMembershipModel(group_id=group.id, member_id=OTHER_ID))
    session.commit()
    return group.id


def _regular_group(session, name="Casa") -> int:
    group = GroupService(GroupRepository(session)).create(name, CREATOR_ID)
    session.add(GroupMembershipModel(group_id=group.id, member_id=OTHER_ID))
    session.commit()
    return group.id


def _service(session, group_id: int) -> ExpenseService:
    return ExpenseService(SQLAlchemyExpenseRepository(session), group_id, GroupRepository(session))


def _occasion(session, group_id: int) -> OccasionService:
    service = _service(session, group_id)
    return OccasionService(service, SQLAlchemyExpenseRepository(session))


def _expense(**overrides) -> ExpenseCreate:
    payload = {
        "description": "Cabaña",
        "amount": 100.0,
        "date": date(2026, 5, 10),
        "category": {"name": "viajes"},
        "payer_id": CREATOR_ID,
        "payment_type": PaymentType.DEBIT,
        "installments": 1,
        "split_strategy": SplitStrategySchema(type="equal", participant_ids=None),
    }
    payload.update(overrides)
    return ExpenseCreate(**payload)


# ---------------------------------------------------------------------------
# Creating the group
# ---------------------------------------------------------------------------


def test_create_a_one_time_group(populated_session):
    """The type is stored and readable back."""
    group_id = _one_time_group(populated_session)

    group = GroupRepository(populated_session).get(group_id)
    assert group.group_type == GroupType.ONE_TIME


def test_groups_default_to_regular(populated_session):
    """Omitting the type keeps today's behaviour."""
    group_id = _regular_group(populated_session)

    assert GroupRepository(populated_session).get(group_id).group_type == GroupType.REGULAR


# ---------------------------------------------------------------------------
# Credit is blocked
# ---------------------------------------------------------------------------


def test_credit_expense_is_rejected_in_a_one_time_group(populated_session):
    """Installments spread cost across months, which is what this group type discards."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)

    with pytest.raises(ValueError):
        service.create_expense(_expense(payment_type=PaymentType.CREDIT, installments=3))


def test_single_installment_credit_is_also_rejected(populated_session):
    """Even 1 cuota is a credit expense, which lands in next month's share."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)

    with pytest.raises(ValueError):
        service.create_expense(_expense(payment_type=PaymentType.CREDIT, installments=1))


def test_credit_expense_still_works_in_a_regular_group(populated_session):
    """The rule is scoped to one-time groups and must not leak."""
    group_id = _regular_group(populated_session)
    service = _service(populated_session, group_id)

    created = service.create_expense(_expense(payment_type=PaymentType.CREDIT, installments=3))

    assert created.id is not None


def test_debit_expense_works_in_a_one_time_group(populated_session):
    """The normal path is unaffected."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)

    created = service.create_expense(_expense())

    assert created.id is not None


# ---------------------------------------------------------------------------
# Aggregating across months
# ---------------------------------------------------------------------------


def test_aggregate_balances_sum_across_months(populated_session):
    """Two expenses in different months produce one balance per member.

    Fran pays 100 in May and 50 in June, split equally with Guada, so Guada owes 75 in total.
    """
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)
    service.create_expense(_expense(amount=100.0, date=date(2026, 5, 10)))
    service.create_expense(_expense(amount=50.0, date=date(2026, 6, 10)))

    aggregate = _occasion(populated_session, group_id).get_aggregate_balance()

    assert len(aggregate.expenses) == 2
    assert aggregate.balances[OTHER_ID] == pytest.approx(-75.0)
    assert aggregate.balances[CREATOR_ID] == pytest.approx(75.0)


def test_aggregate_totals_net_to_zero(populated_session):
    """Whatever the split, the balances of a group must cancel out."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)
    service.create_expense(_expense(amount=100.0, date=date(2026, 5, 10)))
    service.create_expense(_expense(amount=33.33, date=date(2026, 7, 2), payer_id=OTHER_ID))

    aggregate = _occasion(populated_session, group_id).get_aggregate_balance()

    assert sum(aggregate.balances.values()) == pytest.approx(0.0, abs=0.01)


def test_aggregate_is_not_settled_while_any_month_is_open(populated_session):
    """is_settled is an all-months property, not any-month."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)
    service.create_expense(_expense(date=date(2026, 5, 10)))
    service.create_expense(_expense(date=date(2026, 6, 10)))
    service.settle_monthly_share(2026, 5)

    assert _occasion(populated_session, group_id).get_aggregate_balance().is_settled is False


def test_settle_all_closes_every_month(populated_session):
    """One settle closes the whole occasion."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)
    service.create_expense(_expense(date=date(2026, 5, 10)))
    service.create_expense(_expense(date=date(2026, 6, 10)))

    aggregate = _occasion(populated_session, group_id).settle_all()

    assert aggregate.is_settled is True


def test_aggregate_on_an_empty_group_is_settled_and_balanced(populated_session):
    """No expenses means nothing outstanding — and must not raise."""
    group_id = _one_time_group(populated_session)

    aggregate = _occasion(populated_session, group_id).get_aggregate_balance()

    assert aggregate.expenses == []
    assert aggregate.balances == {}


def test_unsettle_all_reopens_every_month(populated_session):
    """The mirror of settle-all: an occasion settled as one thing reopens as one thing."""
    group_id = _one_time_group(populated_session)
    service = _service(populated_session, group_id)
    service.create_expense(_expense(date=date(2026, 5, 10)))
    service.create_expense(_expense(date=date(2026, 6, 10)))
    _occasion(populated_session, group_id).settle_all()

    aggregate = _occasion(populated_session, group_id).unsettle_all()

    assert aggregate.is_settled is False


def test_is_one_time_group_flag(populated_session):
    """The router guards on this, so it must be right for both types."""
    assert _service(populated_session, _one_time_group(populated_session)).is_one_time_group() is True
    assert _service(populated_session, _regular_group(populated_session)).is_one_time_group() is False
