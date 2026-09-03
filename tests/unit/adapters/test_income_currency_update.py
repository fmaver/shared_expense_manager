"""Unit tests for currency edits on recurring income / personal expense — in-memory SQLite.

Regression cover for the currency-propagation fix: a template's currency must be
editable, and the edit must re-sync the snapshots from the viewed month onwards
(past months stay frozen, matching the existing forward-only semantics).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupModel, MemberModel
from template.adapters.repositories import (
    IncomeRepository,
    RecurringPersonalExpenseRepository,
)
from template.domain.models.group import GroupStatus, GroupType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session():
    """Return a fresh in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    """Session with one personal group and one member pre-inserted."""
    group = GroupModel(id=99, name="Personal", status=GroupStatus.ACTIVE, group_type=GroupType.PERSONAL)
    member = MemberModel(id=1, name="Fran", email="fran@example.com", telephone="5411111111")
    session.add_all([group, member])
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Recurring income
# ---------------------------------------------------------------------------


def test_update_recurring_income_can_change_currency(populated_session):
    """A recurring income template's currency must be editable ARS → USD."""
    repo = IncomeRepository(populated_session)
    template = repo.create_recurring(
        owner_member_id=1,
        personal_group_id=99,
        label="Sueldo",
        amount=4000.0,
        start_year=2025,
        start_month=1,
        currency="ARS",
    )

    updated = repo.update_recurring(template.id, currency="USD")

    assert updated.currency == "USD"


def test_update_recurring_income_currency_omitted_is_preserved(populated_session):
    """Omitting currency on an update must not reset it to ARS."""
    repo = IncomeRepository(populated_session)
    template = repo.create_recurring(
        owner_member_id=1,
        personal_group_id=99,
        label="Sueldo",
        amount=4000.0,
        start_year=2025,
        start_month=1,
        currency="USD",
    )

    updated = repo.update_recurring(template.id, amount=4500.0)

    assert updated.currency == "USD"


def test_update_income_instance_can_change_currency(populated_session):
    """A one-off (variable) income entry's currency must be editable."""
    repo = IncomeRepository(populated_session)
    instance = repo.create_variable_instance(
        personal_group_id=99,
        owner_member_id=1,
        year=2025,
        month=6,
        label="Bono",
        amount=1000.0,
        currency="ARS",
    )

    updated = repo.update_instance(instance.id, currency="USD")

    assert updated.currency == "USD"


def test_recurring_income_snapshots_resync_currency_from_month_onwards(populated_session):
    """Editing a template's currency re-syncs snapshots from the viewed month onwards.

    The earlier month must stay untouched (forward-only semantics).
    """
    repo = IncomeRepository(populated_session)
    template = repo.create_recurring(
        owner_member_id=1,
        personal_group_id=99,
        label="Sueldo",
        amount=4000.0,
        start_year=2025,
        start_month=1,
        currency="ARS",
    )
    for month in (5, 6, 7):
        repo.upsert_recurring_instance(
            personal_group_id=99,
            owner_member_id=1,
            year=2025,
            month=month,
            recurring_income_id=template.id,
            label="Sueldo",
            amount=4000.0,
            currency="ARS",
        )

    repo.update_recurring_instances_from_month_onwards(
        personal_group_id=99,
        recurring_income_id=template.id,
        year=2025,
        month=6,
        new_label="Sueldo",
        new_amount=4000.0,
        new_currency="USD",
    )

    by_month = {i.month: i.currency for i in repo.list_instances_for_month(99, 2025, 5)}
    assert by_month[5] == "ARS", "past months must stay frozen"
    assert repo.list_instances_for_month(99, 2025, 6)[0].currency == "USD"
    assert repo.list_instances_for_month(99, 2025, 7)[0].currency == "USD"


# ---------------------------------------------------------------------------
# Recurring personal expense
# ---------------------------------------------------------------------------


def test_update_recurring_personal_expense_can_change_currency(populated_session):
    """A recurring personal expense template's currency must be editable."""
    repo = RecurringPersonalExpenseRepository(populated_session)
    template = repo.create(
        personal_group_id=99,
        owner_member_id=1,
        label="Netflix",
        amount=15.0,
        category_name="entretenimiento",
        start_year=2025,
        start_month=1,
        currency="ARS",
    )

    updated = repo.update(template.id, currency="USD")

    assert updated.currency == "USD"


def test_recurring_expense_snapshots_resync_currency_from_month_onwards(populated_session):
    """Editing a recurring expense's currency re-syncs snapshots forward only."""
    repo = RecurringPersonalExpenseRepository(populated_session)
    template = repo.create(
        personal_group_id=99,
        owner_member_id=1,
        label="Netflix",
        amount=15.0,
        category_name="entretenimiento",
        start_year=2025,
        start_month=1,
        currency="ARS",
    )
    for month in (5, 6):
        repo.upsert_instance(
            personal_group_id=99,
            recurring_expense_id=template.id,
            year=2025,
            month=month,
            label="Netflix",
            amount=15.0,
            category_name="entretenimiento",
            currency="ARS",
        )

    repo.update_instances_from_month_onwards(
        personal_group_id=99,
        recurring_expense_id=template.id,
        year=2025,
        month=6,
        new_label="Netflix",
        new_amount=15.0,
        new_category_name="entretenimiento",
        new_currency="USD",
    )

    assert repo.list_instances_for_month(99, 2025, 5)[0].currency == "ARS"
    assert repo.list_instances_for_month(99, 2025, 6)[0].currency == "USD"
