"""Category API endpoints."""

from typing import List

from fastapi import APIRouter

from template.domain.models.category import Category
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import CategoryResponse, CategoryWithEmojiResponse

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("/", response_model=ResponseModel[CategoryResponse])
async def get_categories() -> ResponseModel[CategoryResponse]:
    """Get all available categories."""
    categories = Category.get_categories()
    return ResponseModel(data=CategoryResponse(categories=list(categories)))


@router.get("/with-emojis", response_model=ResponseModel[List[CategoryWithEmojiResponse]])
async def get_categories_with_emojis() -> ResponseModel[List[CategoryWithEmojiResponse]]:
    """Get all available categories with their corresponding emojis."""
    categories = Category.get_categories()
    categories_with_emojis = [
        CategoryWithEmojiResponse(name=cat, emoji=Category.get_category_emoji(cat)) for cat in categories
    ]
    return ResponseModel(data=categories_with_emojis)
