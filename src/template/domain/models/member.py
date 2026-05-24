"""Module for managing members."""

from datetime import datetime
from typing import Optional

from pydantic import Field

from ..schema_model import CamelCaseModel
from .enums import NotificationType


class Member(CamelCaseModel):
    """Member domain model."""

    id: int = Field(..., description="Unique identifier for the member")
    name: str = Field(..., min_length=1, max_length=100, description="Name of the member")
    telephone: Optional[str] = Field(None, description="Telephone number of the member")
    email: Optional[str] = Field(None, description="Email address of the member")
    hashed_password: str | None = Field(None, description="Hashed password for the member")
    phone_verified_at: datetime | None = Field(None, description="When the phone was verified via WhatsApp")
    notification_preference: NotificationType = Field(
        default=NotificationType.NONE, description="Preferred notification method for the member"
    )
    last_wpp_chat_datetime: datetime | None = Field(None, description="Last WhatsApp chat datetime")

    @property
    def is_stub(self) -> bool:
        """True if this member has no password set (not yet claimed)."""
        return self.hashed_password is None
