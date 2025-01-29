"""Authentication API endpoints."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from template.domain.models.member import Member
from template.domain.schemas.member import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    PasswordUpdate,
    Token,
)
from template.service_layer.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AuthService,
    get_auth_service,
    get_current_member,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class SetPasswordRequest(BaseModel):
    current_password: str | None = None  # Optional for members without password
    new_password: str


class InitialPasswordSetup(BaseModel):
    """Request model for initial password setup."""

    email: str
    new_password: str


@router.post("/register", response_model=MemberResponse)
def register(member: MemberCreate, auth_service: AuthService = Depends(get_auth_service)):
    """Register a new member."""
    db_member = auth_service.get_member_by_email(email=member.email)
    if db_member:
        raise HTTPException(status_code=400, detail="Email already registered")
    return auth_service.create_member(member)


@router.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), auth_service: AuthService = Depends(get_auth_service)):
    """Login endpoint."""
    member = auth_service.authenticate_member(form_data.username, form_data.password)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth_service.create_access_token(data={"sub": member.email}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}


@router.patch("/me", response_model=MemberResponse)
async def update_member_info(
    update_data: MemberUpdate,
    current_member: Member = Depends(get_current_member),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Update the current member's information."""
    try:
        updated_member = auth_service.update_member(current_member, update_data)
        return updated_member
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/me/password", response_model=MemberResponse)
async def update_password(
    password_data: PasswordUpdate,
    current_member: Member = Depends(get_current_member),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Update the current member's password."""
    if not auth_service.verify_password(password_data.current_password, current_member.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")

    updated_member = auth_service.update_member_password(current_member, password_data.new_password)
    return updated_member


@router.get("/me", response_model=MemberResponse)
async def get_current_member_info(current_member: Member = Depends(get_current_member)):
    """Get the current member's information."""
    return current_member


@router.post("/set-password", response_model=MemberResponse)
async def set_password(
    password_data: SetPasswordRequest,
    current_member=Depends(get_current_member),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Set or update password for an existing member."""

    # If member already has a password, verify the current password
    if current_member.hashed_password:
        if not password_data.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is required")
        if not auth_service.verify_password(password_data.current_password, current_member.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")

    # Update the password
    updated_member = auth_service.update_member_password(current_member, password_data.new_password)
    return updated_member


@router.post("/initial-setup", response_model=MemberResponse)
async def initial_password_setup(
    password_data: InitialPasswordSetup, auth_service: AuthService = Depends(get_auth_service)
):
    """Set initial password for an existing member that doesn't have one."""
    member = auth_service.get_member_by_email(password_data.email)

    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Member already has a password set. Use the login endpoint."
        )

    # Set the initial password
    updated_member = auth_service.update_member_password(member, password_data.new_password)
    return updated_member
