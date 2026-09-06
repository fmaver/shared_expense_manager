"""Decide qué recordatorios de vencimiento salen hoy, y los manda.

Separado del loop a propósito: acá está toda la lógica y se prueba pasándole una fecha, sin
esperar ni dormir. El loop solo decide cuándo llamar a esto.
"""

import logging
from datetime import datetime
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from template.adapters.repositories import (
    DueDateReminderRepository,
    DueDateRepository,
    GroupRepository,
)
from template.domain.models.due_date import DueDateRule
from template.domain.models.member import Member
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

    def _recipients(self, group_id: int) -> List[Member]:
        """Los miembros del grupo que no lo archivaron."""
        archived = set(self._groups.list_archived_member_ids(group_id))
        return [m for m in self._groups.list_members(group_id) if m.id not in archived]

    async def _notify(self, due_date: Any, occurrence: Any, members: List[Member], group_name: Optional[str]) -> None:
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
