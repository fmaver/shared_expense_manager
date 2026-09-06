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
from template.domain.schemas.due_date import DueDateReminderRunResponse
from template.service_layer.due_date_service import (
    DueDateReminderService,
    now_in_buenos_aires,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _assert_task_secret(provided: Optional[str]) -> None:
    """404 si no hay secreto configurado, 401 si no coincide."""
    expected = os.getenv("TASK_SECRET")
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    # Comparación en tiempo constante: el secreto es largo y fijo, y esto no cuesta nada.
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid task secret")


@router.post("/due-date-reminders", response_model=ResponseModel[DueDateReminderRunResponse])
async def run_due_date_reminders(
    x_task_secret: Optional[str] = Header(default=None, alias="X-Task-Secret"),
    db: Session = Depends(get_db),
) -> ResponseModel[DueDateReminderRunResponse]:
    """Correr ahora el envío de recordatorios. Idempotente: repetirlo no duplica avisos."""
    _assert_task_secret(x_task_secret)
    sent = await DueDateReminderService(db).run(now_in_buenos_aires())
    return ResponseModel(data=DueDateReminderRunResponse(sent=sent))
