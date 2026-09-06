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
from template.service_layer.due_date_service import (
    DueDateReminderService,
    now_in_buenos_aires,
)

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


def seconds_until_next_hour(now: datetime) -> float:
    """Segundos hasta el próximo :00.

    Dormir un plazo fijo haría que la hora de envío dependa de cuándo arrancó el proceso;
    alineado al reloj, el aviso sale siempre a la misma hora.
    """
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()


async def _run_once() -> None:
    """Una pasada del servicio. Nunca propaga: una vuelta rota no puede matar el loop."""
    try:
        with SessionLocal() as session:
            sent = await DueDateReminderService(session).run(now_in_buenos_aires())
        if sent:
            logger.info("Due date reminders sent: %s", sent)
    except Exception:  # pylint: disable=broad-except
        # Mañana hay otro vencimiento. La cancelación del shutdown no cae acá:
        # CancelledError hereda de BaseException.
        logger.exception("Due date reminder pass failed")


async def _loop() -> None:
    """Correr al arrancar, y después una vez por hora en punto.

    La corrida al arranque no es una optimización: dormir primero deja el feature inservible
    en cualquier servicio que se apague por inactividad, porque lo apagan antes de que el loop
    haya hecho nada. Así, alcanza con que el proceso esté vivo en algún momento de la ventana
    del día, en vez de justo a una hora exacta. Es seguro porque el job es idempotente: la
    tabla de recordatorios impide que correr de más duplique un aviso.
    """
    while True:
        await _run_once()
        await asyncio.sleep(seconds_until_next_hour(datetime.now()))


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
