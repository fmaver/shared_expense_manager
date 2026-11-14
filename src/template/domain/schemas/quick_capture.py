"""Esquemas de carga rápida (atajo de iOS y borradores). camelCase en el cable."""

from datetime import datetime
from typing import Literal, Optional

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


class QuickCaptureAction(CamelCaseModel):
    """One button of the shortcut's menu; `group_id` only for "confirm"."""

    label: str
    action: Literal["confirm", "keep", "discard"]
    group_id: Optional[int] = None


class QuickCaptureResult(CamelCaseModel):
    """What the shortcut shows after a capture. Texts are built here so the shortcut stays dumb."""

    draft_id: int
    status: Literal["read", "unreadable"]
    summary: str
    warning: Optional[str] = None
    actions: list[QuickCaptureAction]
    message: Optional[str] = None


class QuickCaptureConfirm(CamelCaseModel):
    group_id: int


class QuickCaptureMessage(CamelCaseModel):
    """Text for the shortcut's closing notification."""

    message: str
