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
    """Create a group.

    `personal` is deliberately not accepted: personal groups are created only by
    get_or_create_personal_group, and minting one here would give a member a second.
    """

    name: str = Field(..., min_length=1, max_length=255)
    group_type: Literal["regular", "one_time"] = "regular"


class GroupUpdate(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class GroupInvite(CamelCaseModel):
    email: str


class GroupMemberCreate(CamelCaseModel):
    """Add a member by name alone — no contact details, no account, no notification."""

    name: str = Field(..., min_length=1, max_length=100)


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
    is_existing_member: bool = False
    status: InvitationStatus


class InvitationAcceptRequest(CamelCaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class GroupJoinRequest(CamelCaseModel):
    """Join by link. Credentials are required only when joining without an account —
    an authenticated caller supplies none of them, so the service validates rather than
    the schema, letting the error say which path is missing what."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[str] = None
    password: Optional[str] = None
    claim_member_id: Optional[int] = None


class ClaimableMemberResponse(CamelCaseModel):
    """A name-only member that someone joining by link may claim as themselves."""

    member_id: int
    name: str


class GroupJoinResolveResponse(CamelCaseModel):
    group_name: str
    inviter_name: str
    claimable_members: list[ClaimableMemberResponse] = []
    already_member: bool = False


class GroupResponse(CamelCaseModel):
    id: int
    name: str
    status: GroupStatus
    group_type: GroupType
    created_at: Optional[datetime] = None
    members: list[GroupMemberResponse] = Field(default_factory=list)
