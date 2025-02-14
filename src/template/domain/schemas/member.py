"""Member schemas"""

from pydantic import BaseModel, EmailStr

from template.domain.models.enums import NotificationType
from template.domain.schema_model import CamelCaseModel


class MemberBase(CamelCaseModel):
    name: str
    telephone: str
    email: EmailStr
    notification_preference: NotificationType = NotificationType.NONE


class MemberCreate(MemberBase):
    password: str


class MemberUpdate(BaseModel):
    name: str | None = None
    telephone: str | None = None
    email: EmailStr | None = None
    notification_preference: NotificationType | None = None


class NotificationPreferenceUpdate(BaseModel):
    notification_preference: NotificationType


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


class MemberLogin(BaseModel):
    email: EmailStr
    password: str


class MemberResponse(MemberBase):
    """Response model for member data."""

    id: int
    name: str
    telephone: str
    email: EmailStr
    notification_preference: NotificationType

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: str | None = None
