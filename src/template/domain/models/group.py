"""Group domain model."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from template.domain.schema_model import CamelCaseModel


class GroupStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    DELETED = "deleted"


class GroupType(str, Enum):
    REGULAR = "regular"
    PERSONAL = "personal"


class Group(CamelCaseModel):
    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255)
    status: GroupStatus = GroupStatus.ACTIVE
    group_type: GroupType = GroupType.REGULAR
    owner_member_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
