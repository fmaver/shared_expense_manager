"""Member entrypoint"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import MemberRepository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.member import MemberResponse

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=ResponseModel[list[MemberResponse]])
async def get_members(db: Session = Depends(get_db)) -> ResponseModel[list[MemberResponse]]:
    """Get all members."""
    repository = MemberRepository(db)
    members = repository.list()

    return ResponseModel(
        data=[
            MemberResponse(id=member.id, name=member.name, telephone=member.telephone, email=member.email)
            for member in members
        ]
    )
