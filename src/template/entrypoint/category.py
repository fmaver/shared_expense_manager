"""Category API endpoints."""
from fastapi import APIRouter

from template.domain.models.category import Category
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import CategoryResponse

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("/", response_model=ResponseModel[CategoryResponse])
async def get_categories() -> ResponseModel[CategoryResponse]:
    """Get all available categories."""
    categories = Category.get_all_categories()
    return ResponseModel(data=CategoryResponse(categories=list(categories)))
