"""Group request/response schemas."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field

from template.domain.models.enums import InvitationChannel, InvitationStatus
from template.domain.models.group import GroupStatus, GroupType
from template.domain.schema_model import CamelCaseModel


class GroupMemberResponse(CamelCaseModel):
    member_id: int
    name: str
    email: Optional[str] = None
    telephone: Optional[str] = None
    is_stub: bool = False
    joined_at: Optional[datetime] = None


class GroupCreate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class GroupUpdate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class GroupInvite(CamelCaseModel):
    email: str


class GroupInviteCreate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    channel: Literal["email", "phone"]
    contact: str = Field(..., description="Email address or phone number depending on channel")


class InvitationResponse(CamelCaseModel):
    id: int
    group_id: int
    group_name: Optional[str] = None
    inviter_name: Optional[str] = None
    channel: InvitationChannel
    target: Optional[str] = None
    status: InvitationStatus
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    share_url: Optional[str] = None


class GroupJoinLinkResponse(CamelCaseModel):
    token: str
    url: str
    created_at: Optional[datetime] = None


class InvitationResolveResponse(CamelCaseModel):
    group_name: str
    inviter_name: str
    known_name: Optional[str] = None
    known_email: Optional[str] = None
    known_phone: Optional[str] = None
    requires_email: bool
    requires_password: bool
    status: InvitationStatus


class InvitationAcceptRequest(CamelCaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: str


class GroupJoinRequest(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str
    password: str


class GroupJoinResolveResponse(CamelCaseModel):
    group_name: str
    inviter_name: str


class GroupResponse(CamelCaseModel):
    id: int
    name: str
    status: GroupStatus
    group_type: GroupType
    created_at: Optional[datetime] = None
    members: list[GroupMemberResponse] = Field(default_factory=list)
