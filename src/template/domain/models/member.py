"""Module for managing members."""

from pydantic import EmailStr, Field

from ..schema_model import CamelCaseModel


class Member(CamelCaseModel):
    """Member domain model."""

    id: int = Field(..., description="Unique identifier for the member")
    name: str = Field(..., min_length=1, max_length=100, description="Name of the member")
    telephone: str = Field(..., pattern=r"^\+?1?\d{9,15}$", description="Telephone number of the member")
    email: EmailStr = Field(..., description="Email address of the member")
    hashed_password: str | None = Field(None, description="Hashed password for the member")
