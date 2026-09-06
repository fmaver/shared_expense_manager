"""Qué avisos salen hoy, y por qué no salen los que no salen."""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupMembershipModel, GroupModel, MemberModel
from template.adapters.repositories import DueDateRepository
from template.domain.schemas.due_date import DueDateCreate, DueDateUpdate
from template.service_layer.due_date_service import DueDateReminderService

GROUP_ID = 1
FRAN, GUADA = 1, 2


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(GroupModel(id=GROUP_ID, name="Depto"))
        for member_id, name in ((FRAN, "Fran"), (GUADA, "Guada")):
            s.add(MemberModel(id=member_id, name=name, email=f"{name.lower()}@e.com", hashed_password="h"))
            s.add(GroupMembershipModel(group_id=GROUP_ID, member_id=member_id))
        s.commit()
        yield s


def _due_date(session, **overrides):
    payload = {
        "label": "Luz",
        "day_of_month": 20,
        "every_n_months": 1,
        "anchor_year": 2026,
        "anchor_month": 1,
        "notify_days_before": 3,
        "category_name": "servicios",
    }
    payload.update(overrides)
    return DueDateRepository(session).create(GROUP_ID, FRAN, DueDateCreate(**payload))


def _run(session, when: datetime):
    with patch.object(DueDateReminderService, "_notify", new=AsyncMock()) as notify:
        sent = asyncio.run(DueDateReminderService(session).run(when))
    return sent, notify


class TestWhenItSends:
    def test_it_sends_exactly_notify_days_before(self, session):
        _due_date(session)
        sent, notify = _run(session, datetime(2026, 10, 17, 9, 0))

        assert sent == 2, "los dos miembros del grupo"
        assert notify.await_count == 1, "una llamada con la lista de miembros"

    def test_it_does_not_send_the_day_before_that(self, session):
        _due_date(session)
        sent, _ = _run(session, datetime(2026, 10, 16, 9, 0))
        assert sent == 0

    def test_it_does_not_send_outside_the_window(self, session):
        """A las 4 de la mañana no se manda nada, aunque el día sea el correcto."""
        _due_date(session)
        sent, _ = _run(session, datetime(2026, 10, 17, 4, 0))
        assert sent == 0

    def test_it_still_sends_late_in_the_day_after_an_outage(self, session):
        _due_date(session)
        sent, _ = _run(session, datetime(2026, 10, 17, 15, 0))
        assert sent == 2

    def test_an_inactive_due_date_sends_nothing(self, session):
        created = _due_date(session)
        DueDateRepository(session).update(created.id, DueDateUpdate(active=False))

        sent, _ = _run(session, datetime(2026, 10, 17, 9, 0))
        assert sent == 0


class TestTimezone:
    def test_late_utc_evening_is_still_the_previous_day_in_argentina(self):
        """El server corre en UTC: a las 00:30 UTC del 18, en Argentina son las 21:30 del 17.

        Sin zona horaria, un vencimiento del día 20 con 3 días de aviso se dispararía el 16
        argentino, un día antes de lo que el usuario configuró.
        """
        from datetime import timezone as tz

        from template.service_layer.due_date_service import BUENOS_AIRES

        utc_moment = datetime(2026, 10, 18, 0, 30, tzinfo=tz.utc)

        assert utc_moment.astimezone(BUENOS_AIRES).date() == date(2026, 10, 17)


class TestIdempotence:
    def test_running_twice_sends_once(self, session):
        _due_date(session)

        first, _ = _run(session, datetime(2026, 10, 17, 9, 0))
        second, _ = _run(session, datetime(2026, 10, 17, 10, 0))

        assert (first, second) == (2, 0)

    def test_a_failed_send_is_retried_on_the_next_pass(self, session):
        """Reservar antes de enviar evita duplicados; liberar al fallar evita perder el aviso."""
        _due_date(session)

        with patch.object(DueDateReminderService, "_notify", new=AsyncMock(side_effect=RuntimeError("boom"))):
            first = asyncio.run(DueDateReminderService(session).run(datetime(2026, 10, 17, 9, 0)))

        second, _ = _run(session, datetime(2026, 10, 17, 10, 0))

        assert first == 0
        assert second == 2, "la reserva se liberó, así que se reintenta"


class TestRecipients:
    def test_members_who_archived_the_group_are_skipped(self, session):
        session.query(GroupMembershipModel).filter(GroupMembershipModel.member_id == GUADA).update(
            {"archived_at": datetime.utcnow()}
        )
        session.commit()
        _due_date(session)

        sent, _ = _run(session, datetime(2026, 10, 17, 9, 0))

        assert sent == 1, "archivar el grupo es decir que no te interesa más"
