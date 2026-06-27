"""Currency rate API endpoints."""

from typing import Optional

from fastapi import APIRouter

from template.domain.schema_model import CamelCaseModel, ResponseModel
from template.service_layer.currency_service import get_rate_response

router = APIRouter(prefix="/currency", tags=["currency"])


class CurrencyRateResponse(CamelCaseModel):
    """Response schema for the current FX rate."""

    rate: Optional[float] = None
    currency: str
    source: str


@router.get("/rate", response_model=ResponseModel[CurrencyRateResponse])
def get_currency_rate() -> ResponseModel[CurrencyRateResponse]:
    """Return the current USD/ARS blue exchange rate (sell price)."""
    return ResponseModel(data=CurrencyRateResponse(**get_rate_response()))
