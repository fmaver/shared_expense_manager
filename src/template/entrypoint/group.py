"""Group API endpoints."""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import (
    GroupJoinLinkRepository,
    GroupRepository,
    InvitationRepository,
    MemberRepository,
)
from template.dependencies import (
    get_group_service,
    get_member_repository,
    get_repository,
)
from template.domain.models.repository import ExpenseRepository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.group import (
    GroupCreate,
    GroupInvite,
    GroupInviteCreate,
    GroupJoinLinkResponse,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
    InvitationResponse,
)
from template.service_layer.auth_service import get_current_member
from template.service_layer.group_service import GroupService
from template.service_layer.invitation_service import (
    GroupJoinLinkService,
    InvitationService,
)
from template.service_layer.notification_service import NotificationService
from template.service_layer.whatsapp_invite_client import MetaWhatsAppInviteClient

router = APIRouter(prefix="/groups", tags=["Groups"])


def _build_invitation_svc(db: Session) -> InvitationService:
    return InvitationService(
        member_repo=MemberRepository(db),
        group_repo=GroupRepository(db),
        invitation_repo=InvitationRepository(db),
        notification_service=NotificationService(),
        wpp_invite_client=MetaWhatsAppInviteClient(),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5173"),
    )


def _build_join_link_svc(db: Session) -> GroupJoinLinkService:
    return GroupJoinLinkService(
        group_repo=GroupRepository(db),
        member_repo=MemberRepository(db),
        join_link_repo=GroupJoinLinkRepository(db),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5173"),
    )


def _to_response(group, members) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        status=group.status,
        group_type=group.group_type,
        created_at=group.created_at,
        members=[
            GroupMemberResponse(
                member_id=m.id,
                name=m.name,
                email=m.email,
                telephone=m.telephone,
                is_stub=m.is_stub,
            )
            for m in members
        ],
    )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[GroupResponse])
async def create_group(
    data: GroupCreate,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> ResponseModel[GroupResponse]:
    """Create a new group with the current member as owner."""
    group = group_service.create(data.name, current_member.id)
    members = group_service.list_members(group.id)
    return ResponseModel(data=_to_response(group, members))


@router.get("/", response_model=ResponseModel[list[GroupResponse]])
async def list_groups(
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> ResponseModel[list[GroupResponse]]:
    """List all groups the current member belongs to."""
    groups = group_service.list_for_member(current_member.id)
    result = [_to_response(g, group_service.list_members(g.id)) for g in groups]
    return ResponseModel(data=result)


@router.get("/{group_id}", response_model=ResponseModel[GroupResponse])
async def get_group(
    group_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> ResponseModel[GroupResponse]:
    """Get a group by ID."""
    group = group_service.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    members = group_service.list_members(group_id)
    return ResponseModel(data=_to_response(group, members))


@router.put("/{group_id}", response_model=ResponseModel[GroupResponse])
async def update_group(
    group_id: int,
    data: GroupUpdate,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> ResponseModel[GroupResponse]:
    """Update a group's name."""
    try:
        group = group_service.update_name(group_id, data.name)
        members = group_service.list_members(group_id)
        return ResponseModel(data=_to_response(group, members))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{group_id}/members", response_model=ResponseModel[list[GroupMemberResponse]])
async def list_group_members(
    group_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> ResponseModel[list[GroupMemberResponse]]:
    """List all members of a group."""
    members = group_service.list_members(group_id)
    return ResponseModel(
        data=[
            GroupMemberResponse(
                member_id=m.id,
                name=m.name,
                email=m.email,
                telephone=m.telephone,
                is_stub=m.is_stub,
            )
            for m in members
        ]
    )


@router.post("/{group_id}/members/invite", status_code=status.HTTP_204_NO_CONTENT)
async def invite_member(
    group_id: int,
    data: GroupInvite,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    member_repo: MemberRepository = Depends(get_member_repository),
) -> None:
    """Invite a member to the group by email (legacy auto-accept; kept for backwards compat)."""
    try:
        group_service.invite_by_email(group_id, data.email, member_repo)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post(
    "/{group_id}/invitations", response_model=ResponseModel[InvitationResponse], status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    group_id: int,
    data: GroupInviteCreate,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[InvitationResponse]:
    """Invite by name+email or name+phone, creating a stub member and sending a notification."""
    try:
        svc = _build_invitation_svc(db)
        result = svc.create_invitation(
            group_id=group_id,
            inviter=current_member,
            name=data.name,
            channel=data.channel,
            contact=data.contact,
        )
        return ResponseModel(data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{group_id}/invitations", response_model=ResponseModel[list[InvitationResponse]])
async def list_invitations(
    group_id: int,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[list[InvitationResponse]]:
    """List pending invitations for a group."""
    svc = _build_invitation_svc(db)
    return ResponseModel(data=svc.list_invitations(group_id))


@router.delete("/{group_id}/invitations/{invitation_token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    group_id: int,
    invitation_token: str,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> None:
    """Revoke a pending invitation."""
    try:
        svc = _build_invitation_svc(db)
        svc.revoke_invitation(token=invitation_token, revoker_member_id=current_member.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{group_id}/join-link", response_model=ResponseModel[GroupJoinLinkResponse])
async def get_join_link(
    group_id: int,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[GroupJoinLinkResponse]:
    """Get (or create) the shareable join link for a group."""
    if not GroupRepository(db).is_member(group_id, current_member.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    svc = _build_join_link_svc(db)
    return ResponseModel(data=svc.get_or_create_link(group_id, current_member.id))


@router.post("/{group_id}/join-link/rotate", response_model=ResponseModel[GroupJoinLinkResponse])
async def rotate_join_link(
    group_id: int,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[GroupJoinLinkResponse]:
    """Rotate the join link token, invalidating any previously shared URLs."""
    if not GroupRepository(db).is_member(group_id, current_member.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    try:
        svc = _build_join_link_svc(db)
        return ResponseModel(data=svc.rotate_link(group_id, current_member.id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{group_id}/members/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    expense_repo: ExpenseRepository = Depends(get_repository),
) -> None:
    """Leave a group. Blocked if the member has an outstanding balance in any unsettled month."""
    try:
        shares = expense_repo.get_all_monthly_shares(group_id)
        member_key = str(current_member.id)
        outstanding = max(
            (abs(share.balances.get(member_key, 0.0)) for share in shares.values() if not share.is_settled),
            default=0.0,
        )
        group_service.leave(group_id, current_member.id, outstanding)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
