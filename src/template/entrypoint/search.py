"""GET /search/expenses — find expenses by text, amount or payer."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from template.dependencies import get_search_service
from template.domain.schema_model import ResponseModel
from template.domain.schemas.search import ExpenseSearchResponse
from template.service_layer.auth_service import get_current_member
from template.service_layer.search_service import NotAMemberError, SearchService

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/expenses", response_model=ResponseModel[ExpenseSearchResponse])
def search_expenses(
    q: str = Query("", max_length=100),
    group_id: Optional[int] = Query(None, alias="groupId"),
    service: SearchService = Depends(get_search_service),
    current_member=Depends(get_current_member),
) -> ResponseModel[ExpenseSearchResponse]:
    """Every group the member is in (and their personal group), or only `groupId`."""
    try:
        return ResponseModel(data=service.search(current_member, q, group_id))
    except NotAMemberError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group") from e
