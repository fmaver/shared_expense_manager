"""Module for managing members."""

from pydantic import Field

from ..schema_model import CamelCaseModel


class Member(CamelCaseModel):
    id: int
    name: str = Field(..., min_length=1, max_length=100)
    telephone: str = Field(..., pattern=r"^\+?1?\d{9,15}$")
