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


class DueDateReminderRunResponse(CamelCaseModel):
    """Resultado de una corrida del job.

    Un modelo y no un `dict`: `ResponseModel` declara `data: S | list[S]` con S acotado a
    CamelCaseModel, así que parametrizarlo con `dict` viola la cota y FastAPI valida el
    contenido contra CamelCaseModel — que no tiene campos — devolviendo `{"data": []}`.
    """

    sent: int
