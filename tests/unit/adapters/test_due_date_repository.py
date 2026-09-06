"""Los repositorios de vencimientos, sobre SQLite en memoria.

`claim` es lo que hace idempotente todo el feature: la segunda llamada con los mismos datos
debe devolver False, y ese False es lo único que impide reenviar la misma notificación.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupModel, MemberModel
from template.adapters.repositories import DueDateReminderRepository, DueDateRepository
from template.domain.schemas.due_date import DueDateCreate, DueDateUpdate

GROUP_ID = 1
MEMBER_ID = 1


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(MemberModel(id=MEMBER_ID, name="Fran", email="fran@example.com", hashed_password="h"))
        s.add(GroupModel(id=GROUP_ID, name="Depto"))
        s.commit()
        yield s


def _payload(**overrides) -> DueDateCreate:
    data = {
        "label": "Luz",
        "day_of_month": 20,
        "every_n_months": 1,
        "anchor_year": 2026,
        "anchor_month": 10,
        "notify_days_before": 3,
        "category_name": "servicios",
    }
    data.update(overrides)
    return DueDateCreate(**data)


class TestDueDateRepository:
    def test_create_then_list(self, session):
        repo = DueDateRepository(session)
        created = repo.create(GROUP_ID, MEMBER_ID, _payload())

        assert created.id is not None
        assert created.label == "Luz"
        assert created.active is True
        assert [d.label for d in repo.list_for_group(GROUP_ID)] == ["Luz"]

    def test_update_changes_only_what_was_sent(self, session):
        repo = DueDateRepository(session)
        created = repo.create(GROUP_ID, MEMBER_ID, _payload())

        updated = repo.update(created.id, DueDateUpdate(notify_days_before=7))

        assert updated.notify_days_before == 7
        assert updated.day_of_month == 20, "un update parcial no debe pisar el resto"

    def test_list_active_excludes_deactivated(self, session):
        repo = DueDateRepository(session)
        created = repo.create(GROUP_ID, MEMBER_ID, _payload())
        repo.update(created.id, DueDateUpdate(active=False))

        assert repo.list_active() == []

    def test_delete_removes_it(self, session):
        repo = DueDateRepository(session)
        created = repo.create(GROUP_ID, MEMBER_ID, _payload())

        repo.delete(created.id)

        assert repo.list_for_group(GROUP_ID) == []


class TestDueDateReminderRepository:
    def test_the_first_claim_wins_and_the_second_does_not(self, session):
        due_date = DueDateRepository(session).create(GROUP_ID, MEMBER_ID, _payload())
        repo = DueDateReminderRepository(session)

        assert repo.claim(due_date.id, MEMBER_ID, date(2026, 10, 20)) is True
        assert repo.claim(due_date.id, MEMBER_ID, date(2026, 10, 20)) is False

    def test_a_different_occurrence_is_claimable_again(self, session):
        """El mes que viene es otro aviso, no el mismo."""
        due_date = DueDateRepository(session).create(GROUP_ID, MEMBER_ID, _payload())
        repo = DueDateReminderRepository(session)

        repo.claim(due_date.id, MEMBER_ID, date(2026, 10, 20))

        assert repo.claim(due_date.id, MEMBER_ID, date(2026, 11, 20)) is True

    def test_release_makes_it_claimable_again(self, session):
        """Lo que permite reintentar cuando el envío falló, sin duplicar cuando no falló."""
        due_date = DueDateRepository(session).create(GROUP_ID, MEMBER_ID, _payload())
        repo = DueDateReminderRepository(session)
        repo.claim(due_date.id, MEMBER_ID, date(2026, 10, 20))

        repo.release(due_date.id, MEMBER_ID, date(2026, 10, 20))

        assert repo.claim(due_date.id, MEMBER_ID, date(2026, 10, 20)) is True
