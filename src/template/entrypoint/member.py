"""Member entrypoint"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import MemberRepository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.member import MemberResponse, MemberUpdate, PasswordUpdate
from template.service_layer.auth_service import (
    AuthService,
    get_auth_service,
    get_current_member,
)

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=ResponseModel[list[MemberResponse]])
async def get_members(db: Session = Depends(get_db)) -> ResponseModel[list[MemberResponse]]:
    """Get all members."""
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
async def get_current_member_info(current_member=Depends(get_current_member)) -> ResponseModel[MemberResponse]:
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
async def update_member_info(
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
async def update_password(
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
