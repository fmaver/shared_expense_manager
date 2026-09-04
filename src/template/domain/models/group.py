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
    """How a group treats time.

    REGULAR is an ongoing arrangement: expenses belong to a month and settlement closes a
    month. ONE_TIME is an occasion — a trip, a dinner — with no notion of "this month": every
    expense belongs to the single event, and one settle closes the whole thing. Monthly shares
    still exist underneath a one-time group; they are aggregated away at the edges.
    """

    REGULAR = "regular"
    PERSONAL = "personal"
    ONE_TIME = "one_time"


class Group(CamelCaseModel):
    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255)
    status: GroupStatus = GroupStatus.ACTIVE
    group_type: GroupType = GroupType.REGULAR
    owner_member_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
