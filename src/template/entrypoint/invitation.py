"""Invitation endpoints — resolve and accept invitations, and register via join links."""

import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
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
from template.domain.schemas.member import MemberResponse, Token
from template.service_layer.auth_service import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY, get_current_member
from template.service_layer.invitation_service import GroupJoinLinkService, InvitationService
from template.service_layer.notification_service import NotificationService
from template.service_layer.whatsapp_invite_client import MockWhatsAppInviteClient

router = APIRouter(tags=["Invitations"])


def _invitation_svc(db: Session = Depends(get_db)) -> InvitationService:
    return InvitationService(
        member_repo=MemberRepository(db),
        group_repo=GroupRepository(db),
        invitation_repo=InvitationRepository(db),
        notification_service=NotificationService(),
        wpp_invite_client=MockWhatsAppInviteClient(),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5173"),
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


@router.get("/invitations/resolve/{token}", response_model=ResponseModel[InvitationResolveResponse])
async def resolve_invitation(
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
async def accept_invitation(
    token: str,
    body: InvitationAcceptRequest,
    svc: InvitationService = Depends(_invitation_svc),
) -> dict:
    """Accept a group invitation. Unauthenticated — the caller sets their password here."""
    try:
        claimed = svc.accept_invitation(
            token=token,
            password=body.password,
            email=body.email,
        )
        access_token = _make_token(claimed.id, claimed.email)
        return {"data": {"accessToken": access_token, "tokenType": "bearer"}}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/join/resolve/{token}", response_model=ResponseModel[GroupJoinResolveResponse])
async def resolve_join_token(
    token: str,
    svc: GroupJoinLinkService = Depends(_join_link_svc),
) -> ResponseModel[GroupJoinResolveResponse]:
    """Resolve a shareable join link. Public — no auth required."""
    try:
        result = svc.resolve_join_token(token)
        return ResponseModel(data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/join/{token}")
async def register_and_join(
    token: str,
    body: GroupJoinRequest,
    svc: GroupJoinLinkService = Depends(_join_link_svc),
) -> dict:
    """Register a new member and add them to the group identified by the join link."""
    try:
        new_member = svc.register_and_join(
            token=token,
            name=body.name,
            email=body.email,
            password=body.password,
        )
        access_token = _make_token(new_member.id, new_member.email)
        return {"data": {"accessToken": access_token, "tokenType": "bearer"}}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
