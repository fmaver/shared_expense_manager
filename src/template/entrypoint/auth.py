"""Authentication API endpoints."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from template.domain.schemas.member import MemberCreate, MemberResponse, Token
from template.service_layer.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AuthService,
    get_auth_service,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


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


@router.post("/initial-password", response_model=MemberResponse)
async def initial_password_setup(
    password_data: InitialPasswordSetup, auth_service: AuthService = Depends(get_auth_service)
):
    """Set initial password for an existing member that doesn't have one."""
    member = auth_service.get_member_by_email(email=password_data.email)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.hashed_password:
        raise HTTPException(status_code=400, detail="Member already has a password set")

    updated_member = auth_service.update_member_password(member, password_data.new_password)
    return updated_member
