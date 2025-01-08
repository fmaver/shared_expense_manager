"""Application configuration - root APIRouter.

Defines all FastAPI application endpoints.

Resources:
    1. https://fastapi.tiangolo.com/tutorial/bigger-applications
"""
from fastapi import APIRouter

from template.entrypoint import (
    category,
    expense,
    member,
    monitor,
    monthly_share,
    whatsapp_bot,
)

api_v1_prefix: str = "/api/v1"

root_router: APIRouter = APIRouter()
api_router_v1: APIRouter = APIRouter(prefix=api_v1_prefix)

# API routers
root_router.include_router(monitor.router)
api_router_v1.include_router(expense.router)
api_router_v1.include_router(member.router)
api_router_v1.include_router(monthly_share.router)
api_router_v1.include_router(category.router)
root_router.include_router(whatsapp_bot.router)
