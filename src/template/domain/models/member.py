"""Module for managing members."""

from datetime import datetime

from pydantic import EmailStr, Field

from ..schema_model import CamelCaseModel
from .enums import NotificationType


class Member(CamelCaseModel):
    """Member domain model."""

    id: int = Field(..., description="Unique identifier for the member")
    name: str = Field(..., min_length=1, max_length=100, description="Name of the member")
    telephone: str = Field(..., pattern=r"^\+?1?\d{9,15}$", description="Telephone number of the member")
    email: EmailStr = Field(..., description="Email address of the member")
    hashed_password: str | None = Field(None, description="Hashed password for the member")
    notification_preference: NotificationType = Field(
        default=NotificationType.NONE, description="Preferred notification method for the member"
    )
    last_wpp_chat_datetime: datetime | None = Field(None, description="Last WhatsApp chat datetime")
