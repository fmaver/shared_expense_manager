"""Member schemas"""
from pydantic import BaseModel, EmailStr

from template.domain.schema_model import CamelCaseModel


class MemberBase(CamelCaseModel):
    name: str
    telephone: str
    email: EmailStr


class MemberCreate(MemberBase):
    password: str


class MemberUpdate(BaseModel):
    name: str | None = None
    telephone: str | None = None
    email: EmailStr | None = None


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

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: str | None = None
