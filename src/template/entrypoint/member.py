"""Member entrypoint"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import MemberRepository
from template.dependencies import get_shortcut_token_service
from template.domain.schema_model import ResponseModel
from template.domain.schemas.member import MemberResponse, MemberUpdate, PasswordUpdate
from template.domain.schemas.quick_capture import (
    ShortcutTokenIssued,
    ShortcutTokenStatus,
)
from template.service_layer.auth_service import (
    AuthService,
    get_auth_service,
    get_current_member,
)
from template.service_layer.shortcut_token_service import ShortcutTokenService

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=ResponseModel[list[MemberResponse]])
def get_members(
    db: Session = Depends(get_db),
    _=Depends(get_current_member),
) -> ResponseModel[list[MemberResponse]]:
    """Get all members.

    Authenticated: this returns every member's name, email and telephone.
    """
    repository = MemberRepository(db)
    members = repository.list()

    return ResponseModel(
        data=[
            MemberResponse(
                id=member.id,
                name=member.name,
                telephone=member.telephone,
                email=member.email,
                notification_preference=member.notification_preference,
                last_wpp_chat_datetime=member.last_wpp_chat_datetime,
            )
            for member in members
        ]
    )


@router.get("/me", response_model=ResponseModel[MemberResponse])
def get_current_member_info(current_member=Depends(get_current_member)) -> ResponseModel[MemberResponse]:
    """Get the current member's information."""
    return ResponseModel(
        data=MemberResponse(
            id=current_member.id,
            name=current_member.name,
            telephone=current_member.telephone,
            email=current_member.email,
            notification_preference=current_member.notification_preference,
            last_wpp_chat_datetime=current_member.last_wpp_chat_datetime,
        )
    )


@router.patch("/me", response_model=ResponseModel[MemberResponse])
def update_member_info(
    update_data: MemberUpdate,
    current_member=Depends(get_current_member),
    auth_service: AuthService = Depends(get_auth_service),
) -> ResponseModel[MemberResponse]:
    """Update the current member's information including notification preferences."""
    try:
        updated_member = auth_service.update_member(current_member, update_data)
        return ResponseModel(
            data=MemberResponse(
                id=updated_member.id,
                name=updated_member.name,
                telephone=updated_member.telephone,
                email=updated_member.email,
                notification_preference=updated_member.notification_preference,
                last_wpp_chat_datetime=updated_member.last_wpp_chat_datetime,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/me/password", response_model=ResponseModel[MemberResponse])
def update_password(
    password_data: PasswordUpdate,
    current_member=Depends(get_current_member),
    auth_service: AuthService = Depends(get_auth_service),
) -> ResponseModel[MemberResponse]:
    """Update the current member's password."""
    if not auth_service.verify_password(password_data.current_password, current_member.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")

    updated_member = auth_service.update_member_password(current_member, password_data.new_password)
    return ResponseModel(
        data=MemberResponse(
            id=updated_member.id,
            name=updated_member.name,
            telephone=updated_member.telephone,
            email=updated_member.email,
            notification_preference=updated_member.notification_preference,
            last_wpp_chat_datetime=updated_member.last_wpp_chat_datetime,
        )
    )


@router.get("/me/shortcut-token", response_model=ResponseModel[ShortcutTokenStatus])
def get_shortcut_token_status(
    current_member=Depends(get_current_member),
    service: ShortcutTokenService = Depends(get_shortcut_token_service),
) -> ResponseModel[ShortcutTokenStatus]:
    """Whether the member has an active shortcut token (never the token itself)."""
    token = service.status(current_member.id)
    if token is None:
        return ResponseModel(data=ShortcutTokenStatus(connected=False))
    return ResponseModel(
        data=ShortcutTokenStatus(
            connected=True, prefix=token.prefix, created_at=token.created_at, last_used_at=token.last_used_at
        )
    )


@router.post(
    "/me/shortcut-token", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[ShortcutTokenIssued]
)
def issue_shortcut_token(
    current_member=Depends(get_current_member),
    service: ShortcutTokenService = Depends(get_shortcut_token_service),
) -> ResponseModel[ShortcutTokenIssued]:
    """Mint a shortcut token (revokes the previous one). The plain token is shown only once."""
    raw, model = service.issue(current_member.id)
    return ResponseModel(data=ShortcutTokenIssued(token=raw, prefix=model.prefix, created_at=model.created_at))


@router.delete("/me/shortcut-token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_shortcut_token(
    current_member=Depends(get_current_member),
    service: ShortcutTokenService = Depends(get_shortcut_token_service),
) -> None:
    """Revoke the member's shortcut token."""
    service.revoke(current_member.id)
