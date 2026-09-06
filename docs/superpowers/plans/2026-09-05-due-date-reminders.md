# Vencimientos de servicios y recordatorios — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un miembro carga una vez cuándo vence un servicio y la app le avisa antes de cada vencimiento, sin volver a cargar nada.

**Architecture:** Una tabla `due_dates` con la regla de fecha (día del mes + cada N meses desde un mes ancla) y una tabla `due_date_reminders` cuya restricción `UNIQUE` es lo que hace idempotente el envío. Un `asyncio.Task` en el `lifespan` despierta alineado al reloj y, a las 09:00 de Argentina, envía lo que corresponda reutilizando el ruteo push→mail que ya existe.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`), Alembic, Pydantic v2 (`CamelCaseModel`), pytest, React 18 + Vite + Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-05-due-date-reminders-design.md`

## Global Constraints

- El paquete se llama `template`. Todos los imports son `from template.xxx import ...`.
- Toda respuesta va envuelta en `ResponseModel[T]` → `{"data": ...}`.
- camelCase en el cable vía `CamelCaseModel`; el front recibe camelCase.
- La plata es `float`, nunca `Decimal`. (En esta fase no hay montos.)
- `make lint` (pre-commit completo) debe pasar antes de cada commit. Verificar el **exit code**, no la ausencia de texto.
- Zona horaria de referencia: `America/Argentina/Buenos_Aires`. Nunca `date.today()` sin zona.
- Hora de envío: **09:00** local. Ventana de seguridad: **09:00–22:00**.
- La migración `m17_due_dates` cuelga de `down_revision = "m16_push_subscriptions"`.
- Destinatarios: miembros del grupo dueño **que no lo tengan archivado**.
- Nunca commitear a `main`. Rama `feat/due-date-reminders` en cada repo, creada desde `origin/main` tras un `git fetch origin --prune`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `src/template/domain/models/due_date.py` | **Nuevo.** `DueDateRule`: toda la aritmética de fechas. Sin DB, sin I/O. |
| `src/template/domain/schemas/due_date.py` | **Nuevo.** `DueDateCreate` / `DueDateUpdate` / `DueDateResponse`. |
| `src/template/adapters/orm.py` | **Modificar.** `DueDateModel`, `DueDateReminderModel`. |
| `src/template/adapters/repositories.py` | **Modificar.** `DueDateRepository`, `DueDateReminderRepository`. |
| `migrations/versions/m17_due_dates.py` | **Nuevo.** Las dos tablas y el índice único. |
| `src/template/service_layer/due_date_service.py` | **Nuevo.** `DueDateReminderService.run()`: a quién avisar hoy, idempotencia, reintento. |
| `src/template/service_layer/due_date_scheduler.py` | **Nuevo.** El loop: dormir hasta el próximo :00, llamar al service. |
| `src/template/service_layer/push_service.py` | **Modificar.** `push_body_for_due_date`. |
| `src/template/service_layer/notification_service.py` | **Modificar.** `notify_due_date`. |
| `src/template/entrypoint/due_date.py` | **Nuevo.** CRUD bajo `/groups/{group_id}/due-dates`. |
| `src/template/entrypoint/tasks.py` | **Nuevo.** `POST /tasks/due-date-reminders`, protegido por secreto. |
| `src/template/dependencies.py` | **Modificar.** Factories de los dos repos. |
| `src/template/router.py` | **Modificar.** Registrar los dos routers nuevos. |
| `src/template/asgi.py` | **Modificar.** Arrancar y frenar el loop en el lifespan. |
| `shared_expense_front/src/api/dueDates.ts` | **Nuevo.** Cliente a mano. |
| `shared_expense_front/src/pages/GroupDueDatesPage.tsx` | **Nuevo.** Pantalla de lista + alta. |
| `shared_expense_front/src/pages/GroupLayout.tsx` | **Modificar.** Pestaña nueva. |
| `shared_expense_front/src/App.tsx` | **Modificar.** Ruta nueva. |

La aritmética de fechas vive sola en `due_date.py` porque es la parte con más casos borde y la única que se puede probar exhaustivamente sin tocar nada más. El loop vive separado del servicio para que el servicio se pueda testear sin esperar ni dormir.

---

## Task 1: Aritmética de fechas

**Files:**
- Create: `src/template/domain/models/due_date.py`
- Test: `tests/unit/domain/models/test_due_date_rule.py`

**Interfaces:**
- Consumes: nada.
- Produces: `DueDateRule(day_of_month: int, every_n_months: int, anchor_year: int, anchor_month: int)` con `occurs_in(year: int, month: int) -> bool`, `occurrence_on(year: int, month: int) -> date` y `next_occurrence(on_or_after: date) -> date`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""La aritmética de vencimientos, que es donde están todos los casos borde."""

from datetime import date

import pytest

from template.domain.models.due_date import DueDateRule


def _monthly(day: int) -> DueDateRule:
    return DueDateRule(day_of_month=day, every_n_months=1, anchor_year=2026, anchor_month=1)


class TestOccurrenceOn:
    def test_a_normal_day_is_that_day(self):
        assert _monthly(20).occurrence_on(2026, 10) == date(2026, 10, 20)

    @pytest.mark.parametrize(
        "year,month,expected_day",
        [(2026, 11, 30), (2026, 2, 28), (2028, 2, 29), (2026, 12, 31)],
    )
    def test_day_31_clamps_to_the_last_day_of_a_short_month(self, year, month, expected_day):
        """Un vencimiento cargado el 31 no se saltea noviembre ni febrero."""
        assert _monthly(31).occurrence_on(year, month) == date(year, month, expected_day)


class TestOccursIn:
    def test_monthly_occurs_every_month(self):
        rule = _monthly(20)
        assert all(rule.occurs_in(2026, m) for m in range(1, 13))

    def test_bimonthly_alternates_from_its_anchor(self):
        """Gas bimestral arrancando en octubre: oct sí, nov no, dic sí."""
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.occurs_in(2026, 10) is True
        assert rule.occurs_in(2026, 11) is False
        assert rule.occurs_in(2026, 12) is True
        assert rule.occurs_in(2027, 2) is True

    def test_nothing_occurs_before_the_anchor(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.occurs_in(2026, 8) is False

    def test_yearly_repeats_the_same_month(self):
        rule = DueDateRule(day_of_month=5, every_n_months=12, anchor_year=2026, anchor_month=3)
        assert rule.occurs_in(2027, 3) is True
        assert rule.occurs_in(2027, 4) is False


class TestNoWeekendShift:
    def test_a_due_date_on_a_sunday_stays_on_the_sunday(self):
        """Decisión del spec: si la boleta dice 20, la app dice 20 aunque sea domingo.

        Este test existe para que la decisión no se "arregle" sin querer más adelante.
        """
        assert _monthly(20).occurrence_on(2026, 9) == date(2026, 9, 20)
        assert date(2026, 9, 20).weekday() == 6, "el 20/09/2026 es domingo"


class TestNextOccurrence:
    def test_today_counts_as_the_next_occurrence(self):
        """Con notify_days_before = 0 el aviso sale el mismo día, así que hoy debe contar."""
        assert _monthly(20).next_occurrence(date(2026, 10, 20)) == date(2026, 10, 20)

    def test_after_the_day_it_rolls_to_the_following_month(self):
        assert _monthly(20).next_occurrence(date(2026, 10, 21)) == date(2026, 11, 20)

    def test_bimonthly_skips_the_month_in_between(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.next_occurrence(date(2026, 10, 16)) == date(2026, 12, 15)

    def test_before_the_anchor_it_returns_the_anchor_month(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.next_occurrence(date(2026, 7, 1)) == date(2026, 10, 15)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `poetry run pytest tests/unit/domain/models/test_due_date_rule.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'template.domain.models.due_date'`

- [ ] **Step 3: Implementar**

```python
"""La regla que convierte "el 20, cada 2 meses, desde octubre" en fechas concretas.

Vive sola y sin dependencias porque es la parte con más casos borde del feature: el día 31 en
meses que no lo tienen, los ciclos que no son mensuales, y el mes desde el que se cuenta.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DueDateRule:
    """Un vencimiento recurrente: día del mes, cada cuántos meses, y desde qué mes.

    `every_n_months = 1` es el caso mensual, así que no hay dos patrones: hay una fórmula.
    El ancla solo importa cuando N > 1, donde distingue "bimestral desde octubre" de
    "bimestral desde noviembre".
    """

    day_of_month: int
    every_n_months: int
    anchor_year: int
    anchor_month: int

    def occurs_in(self, year: int, month: int) -> bool:
        """True si el ciclo cae en este mes. Nada ocurre antes del mes ancla."""
        offset = (year * 12 + month) - (self.anchor_year * 12 + self.anchor_month)
        if offset < 0:
            return False
        return offset % self.every_n_months == 0

    def occurrence_on(self, year: int, month: int) -> date:
        """La fecha concreta en ese mes, sin preguntar si el ciclo cae ahí.

        El día se recorta al último del mes: un vencimiento cargado el 31 cae el 30 en
        noviembre y el 28 en febrero, en lugar de saltearse esos meses.
        """
        last_day = monthrange(year, month)[1]
        return date(year, month, min(self.day_of_month, last_day))

    def next_occurrence(self, on_or_after: date) -> date:
        """La primera ocurrencia en o después de esa fecha.

        "En o después" y no "después": con notify_days_before = 0 el aviso sale el mismo día
        del vencimiento, y ese caso tiene que encontrarse a sí mismo.
        """
        year, month = on_or_after.year, on_or_after.month
        # 14 meses cubre cualquier ciclo de hasta un año más el mes en curso.
        for _ in range(14 + self.every_n_months):
            if self.occurs_in(year, month):
                candidate = self.occurrence_on(year, month)
                if candidate >= on_or_after:
                    return candidate
            month += 1
            if month == 13:
                year, month = year + 1, 1
        raise ValueError(f"No occurrence found after {on_or_after} for {self}")
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `poetry run pytest tests/unit/domain/models/test_due_date_rule.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Lint y commit**

```bash
make lint; echo "lint exit=$?"   # debe ser 0
git add src/template/domain/models/due_date.py tests/unit/domain/models/test_due_date_rule.py
git commit -m "feat(due-dates): regla de fecha recurrente con día, ciclo y ancla"
```

---

## Task 2: Persistencia — ORM, esquemas, repositorios y migración

**Files:**
- Modify: `src/template/adapters/orm.py`
- Modify: `src/template/adapters/repositories.py`
- Create: `src/template/domain/schemas/due_date.py`
- Create: `migrations/versions/m17_due_dates.py`
- Test: `tests/unit/adapters/test_due_date_repository.py`

**Interfaces:**
- Consumes: `DueDateRule` de Task 1.
- Produces:
  - `DueDateModel` (tabla `due_dates`), `DueDateReminderModel` (tabla `due_date_reminders`).
  - `DueDateCreate(label, day_of_month, every_n_months, anchor_year, anchor_month, notify_days_before, category_name)`, `DueDateUpdate` (todos opcionales), `DueDateResponse` (los anteriores + `id`, `group_id`, `active`).
  - `DueDateRepository(session)` con `create(group_id, created_by_member_id, data) -> DueDateResponse`, `list_for_group(group_id) -> list[DueDateResponse]`, `list_active() -> list[DueDateModel]`, `get(due_date_id) -> Optional[DueDateModel]`, `update(due_date_id, data) -> DueDateResponse`, `delete(due_date_id) -> None`.
  - `DueDateReminderRepository(session)` con `claim(due_date_id: int, member_id: int, due_on: date) -> bool` y `release(due_date_id: int, member_id: int, due_on: date) -> None`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""Los repositorios de vencimientos, sobre SQLite en memoria.

`claim` es lo que hace idempotente todo el feature: la segunda llamada con los mismos datos
debe devolver False, y ese False es lo único que impide reenviar la misma notificación.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupModel, MemberModel
from template.adapters.repositories import DueDateRepository, DueDateReminderRepository
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
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `poetry run pytest tests/unit/adapters/test_due_date_repository.py -v`
Expected: FAIL con `ImportError: cannot import name 'DueDateRepository'`

- [ ] **Step 3: Agregar los modelos ORM**

En `src/template/adapters/orm.py`, después de `RecurringGroupExpenseInstanceModel`:

```python
class DueDateModel(Base):
    """Un vencimiento recurrente: la luz, el alquiler, Netflix."""

    __tablename__ = "due_dates"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    label: Mapped[str] = mapped_column(String(255))
    category_name: Mapped[str] = mapped_column(String(50), default="servicios")
    day_of_month: Mapped[int] = mapped_column(Integer)
    every_n_months: Mapped[int] = mapped_column(Integer, default=1)
    anchor_year: Mapped[int] = mapped_column(Integer)
    anchor_month: Mapped[int] = mapped_column(Integer)
    notify_days_before: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    group: Mapped["GroupModel"] = relationship(foreign_keys=[group_id])


class DueDateReminderModel(Base):
    """Un aviso ya enviado.

    El UNIQUE es el mecanismo de seguridad del feature, no un log: es lo que hace que correr
    el job de más no pueda duplicar un aviso, y por eso el disparador puede cambiar sin tocar
    la lógica.
    """

    __tablename__ = "due_date_reminders"
    __table_args__ = (UniqueConstraint("due_date_id", "member_id", "due_on", name="uq_due_date_reminder"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    due_date_id: Mapped[int] = mapped_column(ForeignKey("due_dates.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    due_on: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Agregar a los imports de `orm.py` lo que falte: `Date`, `UniqueConstraint` desde `sqlalchemy`, y `date` desde `datetime`.

- [ ] **Step 4: Agregar los esquemas**

Crear `src/template/domain/schemas/due_date.py`:

```python
"""Esquemas de vencimientos. camelCase en el cable vía CamelCaseModel."""

from typing import Optional

from pydantic import Field

from template.domain.schema_model import CamelCaseModel


class DueDateCreate(CamelCaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    day_of_month: int = Field(..., ge=1, le=31)
    every_n_months: int = Field(default=1, ge=1, le=12)
    anchor_year: int = Field(..., ge=2000, le=2100)
    anchor_month: int = Field(..., ge=1, le=12)
    # 0 es válido: el aviso sale el mismo día del vencimiento.
    notify_days_before: int = Field(default=3, ge=0, le=30)
    category_name: str = Field(default="servicios", min_length=1, max_length=50)


class DueDateUpdate(CamelCaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    every_n_months: Optional[int] = Field(default=None, ge=1, le=12)
    anchor_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    anchor_month: Optional[int] = Field(default=None, ge=1, le=12)
    notify_days_before: Optional[int] = Field(default=None, ge=0, le=30)
    category_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    active: Optional[bool] = None


class DueDateResponse(CamelCaseModel):
    id: int
    group_id: int
    label: str
    category_name: str
    day_of_month: int
    every_n_months: int
    anchor_year: int
    anchor_month: int
    notify_days_before: int
    active: bool
```

- [ ] **Step 5: Agregar los repositorios**

Al final de `src/template/adapters/repositories.py`:

```python
class DueDateRepository:
    """CRUD de vencimientos recurrentes."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _to_response(model: DueDateModel) -> DueDateResponse:
        return DueDateResponse(
            id=model.id,
            group_id=model.group_id,
            label=model.label,
            category_name=model.category_name,
            day_of_month=model.day_of_month,
            every_n_months=model.every_n_months,
            anchor_year=model.anchor_year,
            anchor_month=model.anchor_month,
            notify_days_before=model.notify_days_before,
            active=model.active,
        )

    def create(self, group_id: int, created_by_member_id: int, data: DueDateCreate) -> DueDateResponse:
        """Crear un vencimiento en un grupo."""
        model = DueDateModel(
            group_id=group_id,
            created_by_member_id=created_by_member_id,
            label=data.label,
            category_name=data.category_name,
            day_of_month=data.day_of_month,
            every_n_months=data.every_n_months,
            anchor_year=data.anchor_year,
            anchor_month=data.anchor_month,
            notify_days_before=data.notify_days_before,
            active=True,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_response(model)

    def list_for_group(self, group_id: int) -> list[DueDateResponse]:
        """Todos los vencimientos de un grupo, activos o no."""
        rows = self.session.query(DueDateModel).filter(DueDateModel.group_id == group_id).all()
        return [self._to_response(r) for r in rows]

    def list_active(self) -> list[DueDateModel]:
        """Los vencimientos activos de todos los grupos — lo que recorre el job."""
        return self.session.query(DueDateModel).filter(DueDateModel.active.is_(True)).all()

    def get(self, due_date_id: int) -> Optional[DueDateModel]:
        """Un vencimiento por id, o None."""
        return self.session.query(DueDateModel).filter(DueDateModel.id == due_date_id).first()

    def update(self, due_date_id: int, data: DueDateUpdate) -> DueDateResponse:
        """Update parcial: solo se escriben los campos presentes en el payload."""
        model = self.get(due_date_id)
        if model is None:
            raise ValueError(f"Due date {due_date_id} not found")
        for field, value in data.model_dump(exclude_unset=True, by_alias=False).items():
            setattr(model, field, value)
        self.session.commit()
        self.session.refresh(model)
        return self._to_response(model)

    def delete(self, due_date_id: int) -> None:
        """Borrar un vencimiento; sus recordatorios caen por cascada."""
        model = self.get(due_date_id)
        if model is not None:
            self.session.delete(model)
            self.session.commit()


class DueDateReminderRepository:
    """Reserva y libera el derecho a enviar un aviso concreto."""

    def __init__(self, session: Session):
        self.session = session

    def claim(self, due_date_id: int, member_id: int, due_on: date) -> bool:
        """Reservar el aviso. False si ya estaba reservado — o sea, ya se envió.

        El que decide es el UNIQUE de la base, no una consulta previa: dos procesos podrían
        leer "no existe" a la vez, pero solo uno puede insertar.
        """
        model = DueDateReminderModel(due_date_id=due_date_id, member_id=member_id, due_on=due_on)
        self.session.add(model)
        try:
            self.session.commit()
            return True
        except IntegrityError:
            self.session.rollback()
            return False

    def release(self, due_date_id: int, member_id: int, due_on: date) -> None:
        """Devolver la reserva cuando el envío falló, para que se reintente."""
        self.session.query(DueDateReminderModel).filter(
            DueDateReminderModel.due_date_id == due_date_id,
            DueDateReminderModel.member_id == member_id,
            DueDateReminderModel.due_on == due_on,
        ).delete()
        self.session.commit()
```

Agregar a los imports de `repositories.py`: `from datetime import date`, `from sqlalchemy.exc import IntegrityError`, los dos modelos nuevos y los tres esquemas nuevos.

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `poetry run pytest tests/unit/adapters/test_due_date_repository.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Crear la migración**

Crear `migrations/versions/m17_due_dates.py`:

```python
"""due dates and their sent reminders

Revision ID: m17_due_dates
Revises: m16_push_subscriptions
"""

import sqlalchemy as sa
from alembic import op

revision = "m17_due_dates"
down_revision = "m16_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "due_dates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("created_by_member_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("category_name", sa.String(length=50), nullable=False, server_default="servicios"),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("every_n_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("anchor_year", sa.Integer(), nullable=False),
        sa.Column("anchor_month", sa.Integer(), nullable=False),
        sa.Column("notify_days_before", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "due_date_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("due_date_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["due_date_id"], ["due_dates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("due_date_id", "member_id", "due_on", name="uq_due_date_reminder"),
    )


def downgrade() -> None:
    op.drop_table("due_date_reminders")
    op.drop_table("due_dates")
```

- [ ] **Step 8: Actualizar la cadena de migraciones en los dos CLAUDE.md**

En `CLAUDE.md` (raíz) y `shared_expense_manager/CLAUDE.md`, cambiar `m16_push_subscriptions` por `m16_push_subscriptions` → `m17_due_dates` en la línea de la cadena, y actualizar "Latest migration".

- [ ] **Step 9: Lint, tests y commit**

```bash
make lint; echo "lint exit=$?"   # debe ser 0
make test
git add -A
git commit -m "feat(due-dates): tablas, esquemas, repositorios y migración m17"
```

---

## Task 3: Texto y ruteo de la notificación

**Files:**
- Modify: `src/template/service_layer/push_service.py`
- Modify: `src/template/service_layer/notification_service.py`
- Test: `tests/unit/service/test_due_date_notification.py`

**Interfaces:**
- Consumes: `PushMessage`, `NotificationService._maybe_push(member, push_service, message)` (ya existentes).
- Produces: `push_body_for_due_date(label: str, due_on: date, days_before: int) -> str` y `NotificationService.notify_due_date(due_date_label: str, due_on: date, days_before: int, members: List[Member], group_name: Optional[str], group_id: Optional[int], push_service: Any = None) -> None` (async).

- [ ] **Step 1: Escribir el test que falla**

```python
"""El aviso de vencimiento usa el mismo ruteo que todo lo demás: push, y si no, mail."""

import asyncio
from datetime import date
from unittest.mock import MagicMock, patch

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import push_body_for_due_date


def _member(member_id: int, name: str) -> Member:
    return Member(
        id=member_id,
        name=name,
        telephone=None,
        email=f"{name.lower()}@example.com",
        notification_preference=NotificationType.EMAIL,
    )


def _ghost() -> Member:
    return Member(id=9, name="Tomi", telephone=None, email=None, notification_preference=NotificationType.EMAIL)


def _push(subscribed_ids):
    service = MagicMock()
    service.send_if_subscribed.side_effect = lambda member_id, *_: member_id in subscribed_ids
    return service


class TestPushBody:
    def test_it_names_the_service_and_the_days_left(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 3) == "📅 Luz vence en 3 días (20/10)"

    def test_zero_days_reads_as_today_rather_than_in_0_days(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 0) == "📅 Luz vence hoy (20/10)"

    def test_one_day_is_singular(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 1) == "📅 Luz vence mañana (20/10)"


class TestRouting:
    def test_push_replaces_email_for_subscribed_members(self):
        service = NotificationService()
        push_service = _push({1})

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_due_date(
                    due_date_label="Luz",
                    due_on=date(2026, 10, 20),
                    days_before=3,
                    members=[_member(1, "Fran"), _member(2, "Guada")],
                    group_name="Depto",
                    group_id=4,
                    push_service=push_service,
                )
            )

        assert [c.args[0] for c in send_email.call_args_list] == ["guada@example.com"]

    def test_ghost_members_are_never_contacted(self):
        service = NotificationService()

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_due_date(
                    due_date_label="Luz",
                    due_on=date(2026, 10, 20),
                    days_before=3,
                    members=[_ghost()],
                    group_name="Depto",
                    group_id=4,
                )
            )

        send_email.assert_not_called()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `poetry run pytest tests/unit/service/test_due_date_notification.py -v`
Expected: FAIL con `ImportError: cannot import name 'push_body_for_due_date'`

- [ ] **Step 3: Agregar el texto en `push_service.py`**

Justo antes de `def push_body_for_settlement(`:

```python
def push_body_for_due_date(label: str, due_on: date, days_before: int) -> str:
    """Qué vence y cuándo, en las palabras que se usan al hablar.

    "en 0 días" y "en 1 días" son las dos formas en que un contador de días suena a máquina,
    así que esos dos casos se dicen como los diría una persona.
    """
    when = {0: "hoy", 1: "mañana"}.get(days_before, f"en {days_before} días")
    return f"📅 {label} vence {when} ({due_on.day:02d}/{due_on.month:02d})"
```

Agregar `from datetime import date` a los imports de `push_service.py`.

- [ ] **Step 4: Agregar `notify_due_date` en `notification_service.py`**

Justo antes de `def _create_expense_message(`:

```python
    async def notify_due_date(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        due_date_label: str,
        due_on: date,
        days_before: int,
        members: List[Member],
        group_name: Optional[str] = None,
        group_id: Optional[int] = None,
        push_service: Any = None,
    ) -> None:
        """Avisar que un vencimiento se acerca.

        Push con mail de respaldo, sin rama de WhatsApp: no hay plantilla aprobada para esto y
        el texto libre solo llegaría a quienes hayan chateado en las últimas 24 horas, que es
        justo lo contrario de un recordatorio.
        """
        subject = f"📅 {due_date_label} vence pronto"
        body = push_body_for_due_date(due_date_label, due_on, days_before)
        message = f"📁 *{group_name}*\n\n{body}" if group_name else body

        push_message = (
            PushMessage(
                group_name or subject,
                body,
                f"/groups/{group_id}/due-dates" if group_id else "/groups",
            )
            if push_service is not None
            else None
        )

        for member in members:
            if self._maybe_push(member, push_service, push_message):
                continue
            # `member.email` no es redundante: un miembro fantasma tiene preferencia pero no
            # tiene a dónde recibir nada.
            if member.notification_preference == NotificationType.EMAIL and member.email:
                self._send_email(member.email, subject, message)
```

Agregar `push_body_for_due_date` al import desde `push_service`, y `date` al import de `datetime` si no está.

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `poetry run pytest tests/unit/service/test_due_date_notification.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Ampliar el guard de cableado a `service_layer/`**

`tests/unit/service/test_push_wiring_guard.py` solo escanea `entrypoint/`, así que no vería
esta llamada — que vive en el service layer. Uno de los tres bugs que motivaron el guard (el
saldado desde el chatbot) también estaba fuera de los routers, o sea que el agujero ya existía.

Reemplazar la constante y la función de escaneo por:

```python
SRC = pathlib.Path(__file__).resolve().parents[2].parent / "src" / "template"
# Los routers no son el único lugar que despacha notificaciones: el chatbot lo hace desde el
# service layer, y ahí se coló uno de los tres bugs que este guard existe para evitar.
SCANNED = (SRC / "entrypoint", SRC / "service_layer")

# Se excluye el módulo que las define: ahí los `notify_*` son declaraciones, no llamadas.
EXCLUDED_FILES = {"notification_service.py"}


def _dispatch_sites():
    """Every `notify_*` dispatch in the routers and the service layer, with its keywords."""
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path.name in EXCLUDED_FILES:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                    # Background tasks pass the bound method itself, uncalled.
                    if isinstance(arg, ast.Attribute) and arg.attr.startswith("notify_"):
                        yield path.name, node.lineno, arg.attr, {kw.arg for kw in node.keywords}
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr.startswith("notify_"):
                    yield path.name, node.lineno, func.attr, {kw.arg for kw in node.keywords}
```

Correr y verificar que el guard sigue en verde **y** que ahora encuentra más sitios que antes:

```bash
poetry run pytest tests/unit/service/test_push_wiring_guard.py -v
```
Expected: PASS, con más casos parametrizados que los 10 anteriores.

Verificar que el guard realmente falla, sacando a mano `push_service=` de una llamada en
`whatsapp_service.py`, corriendo el test, y restaurándolo con `git checkout --` **solo si el
archivo no tiene otros cambios sin commitear**.

- [ ] **Step 7: Lint y commit**

```bash
make lint; echo "lint exit=$?"
git add -A
git commit -m "feat(due-dates): texto del aviso, ruteo push/mail y guard extendido al service layer"
```

---

## Task 4: El servicio que decide a quién avisar hoy

**Files:**
- Create: `src/template/service_layer/due_date_service.py`
- Test: `tests/unit/service/test_due_date_reminder_service.py`

**Interfaces:**
- Consumes: `DueDateRule` (Task 1); `DueDateRepository`, `DueDateReminderRepository` (Task 2); `NotificationService.notify_due_date` (Task 3); `GroupRepository.list_members(group_id)` y `GroupRepository.list_archived_member_ids(group_id)` (ya existentes).
- Produces: `BUENOS_AIRES: ZoneInfo`, `SEND_FROM_HOUR = 9`, `SEND_UNTIL_HOUR = 22`, `now_in_buenos_aires() -> datetime`, y `DueDateReminderService(session).run(now_local: datetime) -> int` (async, devuelve cuántos avisos envió).

- [ ] **Step 1: Escribir el test que falla**

```python
"""Qué avisos salen hoy, y por qué no salen los que no salen."""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupMembershipModel, GroupModel, MemberModel
from template.adapters.repositories import DueDateRepository
from template.domain.schemas.due_date import DueDateCreate
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


def _run(session, when: datetime) -> int:
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
        from template.domain.schemas.due_date import DueDateUpdate

        created = _due_date(session)
        DueDateRepository(session).update(created.id, DueDateUpdate(active=False))

        sent, _ = _run(session, datetime(2026, 10, 17, 9, 0))
        assert sent == 0


class TestTimezone:
    def test_late_utc_evening_is_already_the_next_day_nowhere_it_matters(self):
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
        from datetime import datetime as dt

        session.query(GroupMembershipModel).filter(
            GroupMembershipModel.member_id == GUADA
        ).update({"archived_at": dt.utcnow()})
        session.commit()
        _due_date(session)

        sent, _ = _run(session, datetime(2026, 10, 17, 9, 0))

        assert sent == 1, "archivar el grupo es decir que no te interesa más"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `poetry run pytest tests/unit/service/test_due_date_reminder_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'template.service_layer.due_date_service'`

- [ ] **Step 3: Implementar**

```python
"""Decide qué recordatorios de vencimiento salen hoy, y los manda.

Separado del loop a propósito: acá está toda la lógica y se prueba pasándole una fecha, sin
esperar ni dormir. El loop solo decide cuándo llamar a esto.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from template.adapters.repositories import (
    DueDateReminderRepository,
    DueDateRepository,
    GroupRepository,
)
from template.domain.models.due_date import DueDateRule
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import PushService

logger = logging.getLogger(__name__)

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")

# El envío real ocurre en la vuelta de las 09:00. La ventana es una red de seguridad: si la
# app estuvo caída a esa hora, el aviso sale más tarde en vez de perderse, pero nunca de
# madrugada — un push a las 4am por la boleta del gas es cómo se logra que alguien apague las
# notificaciones para siempre.
SEND_FROM_HOUR = 9
SEND_UNTIL_HOUR = 22


def now_in_buenos_aires() -> datetime:
    """La hora local de referencia. El server corre en UTC, donde 'hoy' no es hoy."""
    return datetime.now(BUENOS_AIRES)


class DueDateReminderService:
    """Recorre los vencimientos activos y avisa a quien corresponda."""

    def __init__(self, session: Session):
        self._session = session
        self._due_dates = DueDateRepository(session)
        self._reminders = DueDateReminderRepository(session)
        self._groups = GroupRepository(session)
        self._notifications = NotificationService()
        self._push = PushService(session)

    async def run(self, now_local: datetime) -> int:
        """Enviar los avisos que correspondan a `now_local`. Devuelve cuántos envió.

        Reserva antes de enviar y libera si el envío falla: así el peor caso es una hora de
        demora, en vez de un aviso duplicado o uno perdido para siempre.
        """
        if not SEND_FROM_HOUR <= now_local.hour < SEND_UNTIL_HOUR:
            return 0

        today = now_local.date()
        sent = 0

        for due_date in self._due_dates.list_active():
            rule = DueDateRule(
                day_of_month=due_date.day_of_month,
                every_n_months=due_date.every_n_months,
                anchor_year=due_date.anchor_year,
                anchor_month=due_date.anchor_month,
            )
            occurrence = rule.next_occurrence(today)
            if (occurrence - today).days != due_date.notify_days_before:
                continue

            recipients = self._recipients(due_date.group_id)
            claimed = [m for m in recipients if self._reminders.claim(due_date.id, m.id, occurrence)]
            if not claimed:
                continue

            group = self._groups.get(due_date.group_id)
            try:
                await self._notify(due_date, occurrence, claimed, group.name if group else None)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Due date reminder failed for %s; releasing claims", due_date.id)
                for member in claimed:
                    self._reminders.release(due_date.id, member.id, occurrence)
                continue

            sent += len(claimed)

        return sent

    def _recipients(self, group_id: int):
        """Los miembros del grupo que no lo archivaron."""
        archived = set(self._groups.list_archived_member_ids(group_id))
        return [m for m in self._groups.list_members(group_id) if m.id not in archived]

    async def _notify(self, due_date, occurrence, members, group_name) -> None:
        """Punto único de envío — los tests lo reemplazan para no mandar nada de verdad."""
        await self._notifications.notify_due_date(
            due_date_label=due_date.label,
            due_on=occurrence,
            days_before=due_date.notify_days_before,
            members=members,
            group_name=group_name,
            group_id=due_date.group_id,
            push_service=self._push,
        )
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `poetry run pytest tests/unit/service/test_due_date_reminder_service.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Asegurar la base de datos de zonas horarias**

`zoneinfo` lee la tz database del sistema, que falta en varias imágenes `python:slim`. Verificar:

```bash
poetry run python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/Argentina/Buenos_Aires'))"
docker-compose build && docker-compose run --rm api python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/Argentina/Buenos_Aires'))"
```

Si falla dentro de Docker con `ZoneInfoNotFoundError`, agregar la dependencia:

```bash
poetry add tzdata
```

- [ ] **Step 6: Lint y commit**

```bash
make lint; echo "lint exit=$?"
git add -A
git commit -m "feat(due-dates): servicio que decide y envía los avisos del día"
```

---

## Task 5: El loop en el lifespan

**Files:**
- Create: `src/template/service_layer/due_date_scheduler.py`
- Modify: `src/template/asgi.py`
- Test: `tests/unit/service/test_due_date_scheduler.py`

**Interfaces:**
- Consumes: `DueDateReminderService`, `now_in_buenos_aires` (Task 4).
- Produces: `seconds_until_next_hour(now: datetime) -> float`, `start_due_date_scheduler() -> Optional[asyncio.Task]`, `stop_due_date_scheduler() -> None`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""El loop duerme hasta el próximo :00, no una hora fija.

Con sleep(3600) la hora de envío depende de cuándo arrancó el proceso, así que cambia después
de cada deploy y "¿a qué hora avisa?" deja de tener respuesta.
"""

from datetime import datetime

import pytest

from template.service_layer.due_date_scheduler import seconds_until_next_hour


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 10, 17, 8, 0, 0), 3600.0),
        (datetime(2026, 10, 17, 8, 59, 0), 60.0),
        (datetime(2026, 10, 17, 8, 30, 30), 1770.0),
        (datetime(2026, 10, 17, 23, 59, 59), 1.0),
    ],
)
def test_it_sleeps_until_the_top_of_the_hour(now, expected):
    assert seconds_until_next_hour(now) == expected


def test_it_never_returns_zero():
    """Devolver 0 en el :00 exacto haría girar el loop sin pausa."""
    assert seconds_until_next_hour(datetime(2026, 10, 17, 8, 0, 0)) > 0
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `poetry run pytest tests/unit/service/test_due_date_scheduler.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'template.service_layer.due_date_scheduler'`

- [ ] **Step 3: Implementar**

```python
"""El loop que llama al servicio de recordatorios una vez por hora, alineado al reloj.

Es viable porque el proceso no se duerme: UptimeRobot le pega a /liveness cada 5 minutos. Si
eso dejara de ser cierto, el endpoint POST /tasks/due-date-reminders permite dispararlo desde
afuera sin cambiar nada de la lógica.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from template.adapters.database import SessionLocal
from template.service_layer.due_date_service import DueDateReminderService, now_in_buenos_aires

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


def seconds_until_next_hour(now: datetime) -> float:
    """Segundos hasta el próximo :00.

    Dormir un plazo fijo haría que la hora de envío dependa de cuándo arrancó el proceso;
    alineado al reloj, el aviso sale siempre a la misma hora.
    """
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()


async def _loop() -> None:
    """Despertar cada hora en punto y delegar la decisión al servicio."""
    while True:
        await asyncio.sleep(seconds_until_next_hour(datetime.now()))
        try:
            with SessionLocal() as session:
                sent = await DueDateReminderService(session).run(now_in_buenos_aires())
            if sent:
                logger.info("Due date reminders sent: %s", sent)
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            # Una vuelta que explota no puede matar el loop: mañana hay otro vencimiento.
            logger.exception("Due date reminder pass failed")


def start_due_date_scheduler() -> Optional[asyncio.Task]:
    """Arrancar el loop, salvo que esté apagado por configuración."""
    global _task  # pylint: disable=global-statement
    if os.getenv("DUE_DATE_REMINDERS_ENABLED", "true").lower() != "true":
        logger.info("Due date reminders disabled by configuration")
        return None
    _task = asyncio.create_task(_loop())
    return _task


def stop_due_date_scheduler() -> None:
    """Cancelar el loop en el shutdown."""
    global _task  # pylint: disable=global-statement
    if _task is not None:
        _task.cancel()
        _task = None
```

- [ ] **Step 4: Engancharlo al lifespan**

En `src/template/asgi.py`, dentro de `on_startup`, después de `await InitializationService.initialize()`:

```python
    start_due_date_scheduler()
```

Y dentro de `on_shutdown`:

```python
    stop_due_date_scheduler()
```

Con el import correspondiente:

```python
from template.service_layer.due_date_scheduler import (
    start_due_date_scheduler,
    stop_due_date_scheduler,
)
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `poetry run pytest tests/unit/service/test_due_date_scheduler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Verificar que la app arranca**

```bash
poetry run python -c "from template.asgi import get_application; get_application(); print('app ok')"
```

- [ ] **Step 7: Lint y commit**

```bash
make lint; echo "lint exit=$?"
git add -A
git commit -m "feat(due-dates): loop horario alineado al reloj en el lifespan"
```

---

## Task 6: CRUD de vencimientos

**Files:**
- Create: `src/template/entrypoint/due_date.py`
- Modify: `src/template/dependencies.py`
- Modify: `src/template/router.py`
- Test: `tests/integration/due_date/test_due_date_router.py`

**Interfaces:**
- Consumes: `DueDateRepository` (Task 2), esquemas (Task 2).
- Produces: los cuatro endpoints bajo `/api/v1/groups/{group_id}/due-dates`, y `get_due_date_repository(db) -> DueDateRepository` en `dependencies.py`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""CRUD de vencimientos, incluida la puerta de acceso al grupo."""


def _payload(**overrides):
    data = {
        "label": "Luz",
        "dayOfMonth": 20,
        "everyNMonths": 1,
        "anchorYear": 2026,
        "anchorMonth": 10,
        "notifyDaysBefore": 3,
    }
    data.update(overrides)
    return data


def _create_group(client, auth_headers, name="Depto"):
    response = client.post("/api/v1/groups/", json={"name": name}, headers=auth_headers)
    assert response.status_code in (200, 201)
    return response.json()["data"]["id"]


def test_create_and_list(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    created = client.post(
        f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers
    )
    assert created.status_code == 201
    assert created.json()["data"]["label"] == "Luz"
    assert created.json()["data"]["notifyDaysBefore"] == 3

    listed = client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=auth_headers)
    assert listed.status_code == 200
    assert [d["label"] for d in listed.json()["data"]] == ["Luz"]


def test_update_is_partial(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    created = client.post(
        f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers
    ).json()["data"]

    updated = client.put(
        f"/api/v1/groups/{group_id}/due-dates/{created['id']}",
        json={"notifyDaysBefore": 7},
        headers=auth_headers,
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["notifyDaysBefore"] == 7
    assert updated.json()["data"]["dayOfMonth"] == 20


def test_delete(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    created = client.post(
        f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers
    ).json()["data"]

    assert client.delete(
        f"/api/v1/groups/{group_id}/due-dates/{created['id']}", headers=auth_headers
    ).status_code in (200, 204)
    assert client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=auth_headers).json()["data"] == []


def test_a_non_member_cannot_read_or_write(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    client.post("/api/v1/auth/register", json={
        "name": "Otro", "email": "otro@example.com", "password": "secret123", "telephone": "5411999999"
    })
    token = client.post(
        "/api/v1/auth/token", data={"username": "otro@example.com", "password": "secret123"}
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=other).status_code == 403
    assert client.post(
        f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=other
    ).status_code == 403


def test_day_32_is_rejected(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    response = client.post(
        f"/api/v1/groups/{group_id}/due-dates/", json=_payload(dayOfMonth=32), headers=auth_headers
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `TEST_DATABASE_URL=<staging url> poetry run pytest tests/integration/due_date/ -v`
Expected: FAIL con 404 en todas las rutas (el router no existe)

> Crear también `tests/integration/due_date/__init__.py` vacío si el resto de las carpetas de integración lo tienen.

- [ ] **Step 3: Agregar la factory en `dependencies.py`**

```python
def get_due_date_repository(db: Session = Depends(get_db)) -> DueDateRepository:
    """Get due date repository instance."""
    return DueDateRepository(db)
```

Con su import desde `template.adapters.repositories`.

- [ ] **Step 4: Crear el router**

```python
"""Endpoints de vencimientos recurrentes de un grupo."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from template.adapters.repositories import DueDateRepository, GroupRepository
from template.dependencies import get_due_date_repository, get_group_repository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.due_date import DueDateCreate, DueDateResponse, DueDateUpdate
from template.service_layer.auth_service import get_current_member

router = APIRouter(prefix="/groups/{group_id}/due-dates", tags=["DueDates"])


def _assert_group_membership(group_id: int, current_member, group_repo: GroupRepository) -> None:
    """Raise HTTP 403 if current_member does not belong to group_id."""
    if not group_repo.is_member(group_id, current_member.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")


def _assert_belongs_to_group(due_date_id: int, group_id: int, repo: DueDateRepository) -> None:
    """404 si el vencimiento no existe o es de otro grupo.

    Se comprueba la pertenencia al grupo, no solo la existencia: sin esto, un miembro de
    cualquier grupo podría editar el vencimiento de otro pasando su propio group_id.
    """
    model = repo.get(due_date_id)
    if model is None or model.group_id != group_id:
        raise HTTPException(status_code=404, detail="Due date not found")


@router.get("/", response_model=ResponseModel[List[DueDateResponse]])
def list_due_dates(
    group_id: int,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[List[DueDateResponse]]:
    """Listar los vencimientos del grupo."""
    _assert_group_membership(group_id, current_member, group_repo)
    return ResponseModel(data=repo.list_for_group(group_id))


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[DueDateResponse])
def create_due_date(
    group_id: int,
    data: DueDateCreate,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[DueDateResponse]:
    """Crear un vencimiento en el grupo."""
    _assert_group_membership(group_id, current_member, group_repo)
    return ResponseModel(data=repo.create(group_id, current_member.id, data))


@router.put("/{due_date_id}", response_model=ResponseModel[DueDateResponse])
def update_due_date(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    due_date_id: int,
    data: DueDateUpdate,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[DueDateResponse]:
    """Editar un vencimiento. Update parcial: solo se escribe lo enviado."""
    _assert_group_membership(group_id, current_member, group_repo)
    _assert_belongs_to_group(due_date_id, group_id, repo)
    return ResponseModel(data=repo.update(due_date_id, data))


@router.delete("/{due_date_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_due_date(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    due_date_id: int,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> None:
    """Borrar un vencimiento y sus avisos ya enviados."""
    _assert_group_membership(group_id, current_member, group_repo)
    _assert_belongs_to_group(due_date_id, group_id, repo)
    repo.delete(due_date_id)
```

- [ ] **Step 5: Registrarlo en `router.py`**

Agregar `due_date` al import desde `template.entrypoint` y `api_router_v1.include_router(due_date.router)` junto a los demás.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `TEST_DATABASE_URL=<staging url> poetry run pytest tests/integration/due_date/ -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Lint y commit**

```bash
make lint; echo "lint exit=$?"
make test
git add -A
git commit -m "feat(due-dates): CRUD de vencimientos por grupo"
```

---

## Task 7: Endpoint de disparo manual

**Files:**
- Create: `src/template/entrypoint/tasks.py`
- Modify: `src/template/router.py`
- Test: `tests/integration/due_date/test_tasks_endpoint.py`

**Interfaces:**
- Consumes: `DueDateReminderService`, `now_in_buenos_aires` (Task 4).
- Produces: `POST /api/v1/tasks/due-date-reminders`, con header `X-Task-Secret`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""El disparo manual del job.

Existe para poder probar el feature sin esperar un día, y como salida de emergencia si el loop
interno falla. No usa JWT porque no hay usuario detrás: lo protege un secreto compartido.
"""

import os
from unittest.mock import patch


def test_without_a_configured_secret_the_endpoint_does_not_exist(client):
    """404 y no 401: un endpoint sin proteger no debe anunciar que está ahí."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TASK_SECRET", None)
        response = client.post("/api/v1/tasks/due-date-reminders")
    assert response.status_code == 404


def test_the_wrong_secret_is_rejected(client):
    with patch.dict(os.environ, {"TASK_SECRET": "correcto"}):
        response = client.post(
            "/api/v1/tasks/due-date-reminders", headers={"X-Task-Secret": "incorrecto"}
        )
    assert response.status_code == 401


def test_the_right_secret_runs_the_job(client):
    with patch.dict(os.environ, {"TASK_SECRET": "correcto"}):
        response = client.post(
            "/api/v1/tasks/due-date-reminders", headers={"X-Task-Secret": "correcto"}
        )
    assert response.status_code == 200
    assert "sent" in response.json()["data"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `TEST_DATABASE_URL=<staging url> poetry run pytest tests/integration/due_date/test_tasks_endpoint.py -v`
Expected: FAIL — las tres devuelven 404 porque el router no existe

- [ ] **Step 3: Implementar**

```python
"""Disparadores manuales de trabajos programados.

Protegidos por un secreto compartido y no por JWT: no hay un usuario detrás de un cron. Si el
secreto no está configurado, el endpoint responde 404 en vez de quedar abierto — un endpoint
que ejecuta trabajo sin autenticar es peor que uno que no existe.
"""

import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.domain.schema_model import ResponseModel
from template.service_layer.due_date_service import DueDateReminderService, now_in_buenos_aires

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _assert_task_secret(provided: Optional[str]) -> None:
    """404 si no hay secreto configurado, 401 si no coincide."""
    expected = os.getenv("TASK_SECRET")
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    # Comparación en tiempo constante: el secreto es largo y fijo, y esto no cuesta nada.
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid task secret")


@router.post("/due-date-reminders", response_model=ResponseModel[dict])
async def run_due_date_reminders(
    x_task_secret: Optional[str] = Header(default=None, alias="X-Task-Secret"),
    db: Session = Depends(get_db),
) -> ResponseModel[dict]:
    """Correr ahora el envío de recordatorios. Idempotente: repetirlo no duplica avisos."""
    _assert_task_secret(x_task_secret)
    sent = await DueDateReminderService(db).run(now_in_buenos_aires())
    return ResponseModel(data={"sent": sent})
```

- [ ] **Step 4: Registrarlo en `router.py`**

Agregar `tasks` al import desde `template.entrypoint` y `api_router_v1.include_router(tasks.router)`.

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `TEST_DATABASE_URL=<staging url> poetry run pytest tests/integration/due_date/test_tasks_endpoint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Lint y commit**

```bash
make lint; echo "lint exit=$?"
git add -A
git commit -m "feat(due-dates): endpoint de disparo manual protegido por secreto"
```

---

## Task 8: Cliente de API en el frontend

**Files:**
- Create: `shared_expense_front/src/api/dueDates.ts`
- Modify: `shared_expense_front/src/types/expense.ts`

**Interfaces:**
- Consumes: los endpoints de Task 6.
- Produces: `DueDate`, `DueDateInput`, y `getDueDates(groupId)`, `createDueDate(groupId, input)`, `updateDueDate(groupId, id, input)`, `deleteDueDate(groupId, id)`.

- [ ] **Step 1: Agregar los tipos**

En `src/types/expense.ts`:

```ts
export interface DueDate {
  id: number;
  groupId: number;
  label: string;
  categoryName: string;
  dayOfMonth: number;
  everyNMonths: number;
  anchorYear: number;
  anchorMonth: number;
  notifyDaysBefore: number;
  active: boolean;
}

export interface DueDateInput {
  label: string;
  dayOfMonth: number;
  everyNMonths: number;
  anchorYear: number;
  anchorMonth: number;
  notifyDaysBefore: number;
}
```

- [ ] **Step 2: Escribir el cliente**

```ts
import { config } from '../config/env';
import type { DueDate, DueDateInput } from '../types/expense';

/** Todas las llamadas fetch de este repo mandan el bearer a mano; axios no interviene acá. */
function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function base(groupId: number): string {
  return `${config.apiBaseUrl}/api/v1/groups/${groupId}/due-dates`;
}

export async function getDueDates(groupId: number): Promise<DueDate[]> {
  const response = await fetch(`${base(groupId)}/`, { headers: authHeaders() });
  if (!response.ok) throw new Error('No se pudieron cargar los vencimientos');
  return (await response.json()).data as DueDate[];
}

export async function createDueDate(groupId: number, input: DueDateInput): Promise<DueDate> {
  const response = await fetch(`${base(groupId)}/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error('No se pudo crear el vencimiento');
  return (await response.json()).data as DueDate;
}

export async function updateDueDate(
  groupId: number,
  id: number,
  input: Partial<DueDateInput> & { active?: boolean },
): Promise<DueDate> {
  const response = await fetch(`${base(groupId)}/${id}`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error('No se pudo actualizar el vencimiento');
  return (await response.json()).data as DueDate;
}

export async function deleteDueDate(groupId: number, id: number): Promise<void> {
  const response = await fetch(`${base(groupId)}/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!response.ok) throw new Error('No se pudo borrar el vencimiento');
}
```

- [ ] **Step 3: Verificar los gates**

```bash
cd shared_expense_front
npm run lint
npm run typecheck:ratchet   # debe decir "matching baseline", nunca subir de 43
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add src/api/dueDates.ts src/types/expense.ts
git commit -m "feat(due-dates): cliente de API"
```

---

## Task 9: Pantalla de vencimientos

**Files:**
- Create: `shared_expense_front/src/pages/GroupDueDatesPage.tsx`
- Modify: `shared_expense_front/src/pages/GroupLayout.tsx`
- Modify: `shared_expense_front/src/App.tsx`
- Modify: `shared_expense_front/src/i18n/locales/es.json`, `en.json`

**Interfaces:**
- Consumes: `getDueDates`, `createDueDate`, `deleteDueDate` (Task 8).
- Produces: la ruta `/groups/:groupId/due-dates` y la pestaña que lleva a ella.

- [ ] **Step 1: Agregar las traducciones**

En `src/i18n/locales/es.json`, dentro de `tabs`: `"dueDates": "Vencimientos"`. Y un bloque nuevo `dueDates`:

```json
{
  "title": "Vencimientos",
  "empty": "Todavía no cargaste ningún vencimiento.",
  "add": "Agregar vencimiento",
  "label": "Nombre",
  "dayOfMonth": "Día del mes",
  "everyNMonths": "Cada cuántos meses",
  "notifyDaysBefore": "Avisarme con",
  "daysBefore": "días de anticipación",
  "sameDay": "El mismo día",
  "monthly": "Todos los meses",
  "everyN": "Cada {{n}} meses",
  "delete": "Borrar",
  "save": "Guardar"
}
```

En `en.json`, el mismo bloque con `"dueDates": "Due dates"`, `"empty": "You haven't added any due dates yet."`, `"add": "Add due date"`, `"label": "Name"`, `"dayOfMonth": "Day of month"`, `"everyNMonths": "Every N months"`, `"notifyDaysBefore": "Notify me"`, `"daysBefore": "days in advance"`, `"sameDay": "On the day"`, `"monthly": "Every month"`, `"everyN": "Every {{n}} months"`, `"delete": "Delete"`, `"save": "Save"`.

- [ ] **Step 2: Escribir la pantalla**

```tsx
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { createDueDate, deleteDueDate, getDueDates } from '@/api/dueDates';
import type { DueDate } from '@/types/expense';
import { useScroll } from '@/contexts/ScrollContext';

const TODAY = new Date();

export default function GroupDueDatesPage() {
  const { groupId: gp } = useParams<{ groupId: string }>();
  const groupId = parseInt(gp!, 10);
  const { t } = useTranslation();
  const { notifyScroll } = useScroll();

  const [dueDates, setDueDates] = useState<DueDate[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState('');
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [everyNMonths, setEveryNMonths] = useState(1);
  const [notifyDaysBefore, setNotifyDaysBefore] = useState(3);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDueDates(await getDueDates(groupId));
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  }, [groupId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!label.trim()) return;
    try {
      await createDueDate(groupId, {
        label: label.trim(),
        dayOfMonth,
        everyNMonths,
        // El ancla es el mes en curso: "cada 2 meses" cuenta desde ahora, que es lo que
        // alguien espera al cargarlo hoy.
        anchorYear: TODAY.getFullYear(),
        anchorMonth: TODAY.getMonth() + 1,
        notifyDaysBefore,
      });
      setLabel('');
      await load();
    } catch (error) {
      toast.error((error as Error).message);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteDueDate(groupId, id);
      await load();
    } catch (error) {
      toast.error((error as Error).message);
    }
  };

  const cadence = (d: DueDate) =>
    d.everyNMonths === 1 ? t('dueDates.monthly') : t('dueDates.everyN', { n: d.everyNMonths });

  const advance = (d: DueDate) =>
    d.notifyDaysBefore === 0
      ? t('dueDates.sameDay')
      : `${d.notifyDaysBefore} ${t('dueDates.daysBefore')}`;

  return (
    <div className="flex flex-col flex-1">
      <div
        className="flex-1 overflow-y-auto overflow-x-hidden pb-24 lg:pb-0 p-4 space-y-4"
        onScroll={(e) => notifyScroll((e.target as HTMLDivElement).scrollTop)}
      >
        <form onSubmit={handleAdd} className="rounded-lg border border-border bg-card p-4 space-y-3">
          <input
            className="w-full rounded-md border border-border bg-background px-3 py-2"
            placeholder={t('dueDates.label')}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={255}
          />
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs text-muted-foreground">
              {t('dueDates.dayOfMonth')}
              <input
                type="number"
                min={1}
                max={31}
                value={dayOfMonth}
                onChange={(e) => setDayOfMonth(parseInt(e.target.value, 10) || 1)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              {t('dueDates.everyNMonths')}
              <input
                type="number"
                min={1}
                max={12}
                value={everyNMonths}
                onChange={(e) => setEveryNMonths(parseInt(e.target.value, 10) || 1)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              {t('dueDates.notifyDaysBefore')}
              <input
                type="number"
                min={0}
                max={30}
                value={notifyDaysBefore}
                onChange={(e) => setNotifyDaysBefore(parseInt(e.target.value, 10) || 0)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
              />
            </label>
          </div>
          <button
            type="submit"
            className="w-full rounded-md bg-primary px-3 py-2 text-primary-foreground cursor-pointer"
          >
            {t('dueDates.add')}
          </button>
        </form>

        {loading ? null : dueDates.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('dueDates.empty')}</p>
        ) : (
          <ul className="space-y-2">
            {dueDates.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between rounded-lg border border-border bg-card p-3"
              >
                <div>
                  <p className="font-medium text-foreground">{d.label}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('dueDates.dayOfMonth')} {d.dayOfMonth} · {cadence(d)} · {advance(d)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(d.id)}
                  className="text-xs text-destructive cursor-pointer"
                >
                  {t('dueDates.delete')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Agregar la pestaña y la ruta**

En `src/pages/GroupLayout.tsx`, agregar al array de pestañas, después de `charts`:

```tsx
    { label: t('tabs.dueDates'), path: 'due-dates' },
```

En `src/App.tsx`, junto a las otras rutas hijas de `/groups/:groupId`:

```tsx
        <Route path="due-dates" element={<GroupDueDatesPage />} />
```

con su import: `import GroupDueDatesPage from '@/pages/GroupDueDatesPage';`

- [ ] **Step 4: Verificar los gates**

```bash
cd shared_expense_front
npm run lint
npm run typecheck:ratchet   # "matching baseline"
npm run build
```

- [ ] **Step 5: Probar el flujo de punta a punta**

1. Levantar back (`docker-compose up`) y front (`npm run dev`).
2. Entrar a un grupo → pestaña Vencimientos → crear "Luz", día 20, cada 1 mes, 3 días antes.
3. Verificar que aparece en la lista y que sobrevive a un refresh.
4. Disparar el job a mano y confirmar que llega el push:
   ```bash
   curl -X POST http://localhost:8000/api/v1/tasks/due-date-reminders \
        -H "X-Task-Secret: $TASK_SECRET"
   ```
   Para que dispare hoy, crear un vencimiento cuyo día sea `hoy + notifyDaysBefore`.
5. Correrlo **dos veces** y confirmar que el segundo devuelve `{"sent": 0}` — esa es la prueba de que la idempotencia funciona en la base real, no solo en SQLite.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(due-dates): pestaña y pantalla de vencimientos"
```

---

## Cierre

- [ ] **Migrar staging** antes de mergear: `DATABASE_URL=<staging neon> poetry run alembic upgrade head`
- [ ] **Variables nuevas en Render**: `TASK_SECRET` (generar con `openssl rand -hex 32`) y, opcionalmente, `DUE_DATE_REMINDERS_ENABLED`
- [ ] **Verificar en staging** que el push llega, disparando el endpoint a mano
- [ ] `superpowers:requesting-code-review` antes de mergear
- [ ] Para producción: `alembic upgrade head` contra prod Neon **antes** del release, y agregar `TASK_SECRET` allá también
