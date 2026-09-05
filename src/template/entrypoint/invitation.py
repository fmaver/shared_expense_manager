"""Invitation endpoints — resolve and accept invitations, and register via join links."""

import os
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import (
    GroupJoinLinkRepository,
    GroupRepository,
    InvitationRepository,
    MemberRepository,
)
from template.domain.schema_model import ResponseModel
from template.domain.schemas.group import (
    GroupJoinRequest,
    GroupJoinResolveResponse,
    InvitationAcceptRequest,
    InvitationResolveResponse,
)
from template.service_layer.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
)
from template.service_layer.invitation_service import (
    GroupJoinLinkService,
    InvitationService,
)
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import PushService
from template.service_layer.whatsapp_invite_client import MetaWhatsAppInviteClient

_oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def _get_optional_member(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(_oauth2_optional),
) -> Optional[Any]:
    """Return the authenticated member if a valid JWT is present, otherwise None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        if not email:
            return None
        return MemberRepository(db).get_member_by_email(email)
    except JWTError:
        return None


router = APIRouter(tags=["Invitations"])


def _invitation_svc(db: Session = Depends(get_db)) -> InvitationService:
    return InvitationService(
        member_repo=MemberRepository(db),
        group_repo=GroupRepository(db),
        invitation_repo=InvitationRepository(db),
        notification_service=NotificationService(),
        wpp_invite_client=MetaWhatsAppInviteClient(),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5173"),
        push_service=PushService(db),
    )


def _join_link_svc(db: Session = Depends(get_db)) -> GroupJoinLinkService:
    return GroupJoinLinkService(
        group_repo=GroupRepository(db),
        member_repo=MemberRepository(db),
        join_link_repo=GroupJoinLinkRepository(db),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5173"),
    )


def _make_token(member_id: int, email: Optional[str]) -> str:
    sub = email or str(member_id)
    data = {"sub": sub}
    return jwt.encode(
        {**data, "exp": __import__("datetime").datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _announce_join(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    background_tasks: BackgroundTasks,
    db: Session,
    group_id: Optional[int],
    joiner: Any,
    claimed_name: Optional[str] = None,
) -> None:
    """Tell the group's existing members that someone joined.

    Best-effort by design: an arrival that cannot be announced must not fail the join the
    person just completed, so an unknown group is skipped rather than raised.
    """
    if group_id is None:
        return
    group_repo = GroupRepository(db)
    group = group_repo.get(group_id)
    if group is None:
        return
    background_tasks.add_task(
        NotificationService().notify_member_joined,
        joiner=joiner,
        members=group_repo.list_members(group_id),
        group_name=group.name,
        group_id=group_id,
        claimed_name=claimed_name,
        push_service=PushService(db),
    )


@router.get("/invitations/resolve/{token}", response_model=ResponseModel[InvitationResolveResponse])
def resolve_invitation(
    token: str,
    svc: InvitationService = Depends(_invitation_svc),
) -> ResponseModel[InvitationResolveResponse]:
    """Resolve an invitation token. Public — no auth required."""
    try:
        result = svc.resolve_token(token)
        return ResponseModel(data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/invitations/{token}/accept")
def accept_invitation(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    token: str,
    body: InvitationAcceptRequest,
    background_tasks: BackgroundTasks,
    current_member: Optional[Any] = Depends(_get_optional_member),
    svc: InvitationService = Depends(_invitation_svc),
    db: Session = Depends(get_db),
) -> dict:
    """Accept a group invitation.

    Existing members: send their JWT — no password needed, they join the group immediately.
    New users (stubs): send password (and email if phone-invited) to create their account.
    """
    try:
        # Read before accepting: accepting is what consumes the token.
        group_id = svc.group_id_for_token(token)
        claimed = svc.accept_invitation(
            token=token,
            password=body.password,
            email=body.email,
            current_member=current_member,
        )
        _announce_join(background_tasks, db, group_id, claimed)
        access_token = _make_token(claimed.id, claimed.email)
        return {"data": {"accessToken": access_token, "tokenType": "bearer"}}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/join/resolve/{token}", response_model=ResponseModel[GroupJoinResolveResponse])
def resolve_join_token(
    token: str,
    current_member: Optional[Any] = Depends(_get_optional_member),
    svc: GroupJoinLinkService = Depends(_join_link_svc),
) -> ResponseModel[GroupJoinResolveResponse]:
    """Resolve a shareable join link. Public, but reads a JWT when one is present.

    With a JWT we can tell the caller they are already in this group, so the page can say so
    instead of offering a join that would no-op.
    """
    try:
        result = svc.resolve_join_token(token)
        if current_member is not None:
            result.already_member = svc.is_member_of_join_group(token, current_member.id)
        return ResponseModel(data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/join/{token}")
def register_and_join(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    token: str,
    body: GroupJoinRequest,
    background_tasks: BackgroundTasks,
    current_member: Optional[Any] = Depends(_get_optional_member),
    svc: GroupJoinLinkService = Depends(_join_link_svc),
    db: Session = Depends(get_db),
) -> dict:
    """Join the group identified by the join link.

    Authenticated callers join with their JWT and need no credentials in the body; claiming a
    ghost then merges it into their account. Anonymous callers register as before.
    """
    try:
        group_id = svc.group_id_for_token(token)
        # Read the ghost's name first: claiming it merges it away, so afterwards there is no
        # row left to say which name the group had been tracking.
        claimed_name = None
        if body.claim_member_id is not None:
            ghost = MemberRepository(db).get(body.claim_member_id)
            claimed_name = ghost.name if ghost else None
        new_member = svc.register_and_join(
            token=token,
            name=body.name,
            email=body.email,
            password=body.password,
            claim_member_id=body.claim_member_id,
            current_member=current_member,
        )
        _announce_join(background_tasks, db, group_id, new_member, claimed_name=claimed_name)
        access_token = _make_token(new_member.id, new_member.email)
        return {"data": {"accessToken": access_token, "tokenType": "bearer"}}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
