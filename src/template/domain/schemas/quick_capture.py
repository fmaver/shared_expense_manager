"""Esquemas de carga rápida (atajo de iOS y borradores). camelCase en el cable."""

from datetime import datetime
from typing import Optional

from template.domain.schema_model import CamelCaseModel


class ShortcutTokenStatus(CamelCaseModel):
    connected: bool
    prefix: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class ShortcutTokenIssued(CamelCaseModel):
    token: str
    prefix: str
    created_at: datetime
