"""Group API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from template.adapters.repositories import MemberRepository
from template.dependencies import get_group_service, get_member_repository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.group import (
    GroupCreate,
    GroupInvite,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
)
from template.service_layer.auth_service import get_current_member
from template.service_layer.group_service import GroupService

router = APIRouter(prefix="/groups", tags=["Groups"])


def _to_response(group, members) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        status=group.status,
        group_type=group.group_type,
        created_at=group.created_at,
        members=[GroupMemberResponse(member_id=m.id, name=m.name, email=m.email) for m in members],
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
    return ResponseModel(data=[GroupMemberResponse(member_id=m.id, name=m.name, email=m.email) for m in members])


@router.post("/{group_id}/members/invite", status_code=status.HTTP_204_NO_CONTENT)
async def invite_member(
    group_id: int,
    data: GroupInvite,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    member_repo: MemberRepository = Depends(get_member_repository),
) -> None:
    """Invite a member to the group by email (auto-accepts if member exists)."""
    try:
        group_service.invite_by_email(group_id, data.email, member_repo)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{group_id}/members/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
) -> None:
    """Leave a group. Blocked if the member has an outstanding balance."""
    try:
        group_service.leave(group_id, current_member.id, 0.0)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
