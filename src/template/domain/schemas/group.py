"""Group request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import Field

from template.domain.models.group import GroupStatus, GroupType
from template.domain.schema_model import CamelCaseModel


class GroupMemberResponse(CamelCaseModel):
    member_id: int
    name: str
    email: str
    joined_at: Optional[datetime] = None


class GroupCreate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class GroupUpdate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class GroupInvite(CamelCaseModel):
    email: str


class GroupResponse(CamelCaseModel):
    id: int
    name: str
    status: GroupStatus
    group_type: GroupType
    created_at: Optional[datetime] = None
    members: list[GroupMemberResponse] = Field(default_factory=list)
