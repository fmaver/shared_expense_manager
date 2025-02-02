"""Application implementation - ASGI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from template.adapters.database import SessionLocal
from template.router import api_router_v1, root_router
from template.service_layer.initialization import InitializationService
from template.settings.api_settings import ApplicationSettings

log = logging.getLogger(__name__)


async def on_startup(app: FastAPI):
    """
    Define FastAPI startup event handler.

    Args:
        app (FastAPI): Application object instance.
    """
    log.debug("Execute FastAPI startup event handler.")

    # Initialize database and default data
    await InitializationService.initialize()

    # Initialize the expense manager with default members
    with SessionLocal() as db:
        app.state.expense_manager = InitializationService.initialize_expense_manager(db)


async def on_shutdown():
    """
    Define FastAPI shutdown event handler.

    Resources:
        1. https://fastapi.tiangolo.com/advanced/events/#shutdown-event
    """
    log.debug("Execute FastAPI shutdown event handler.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Define FastAPI lifespan event handler.

    Args:
        app (FastAPI): Application object instance.

    Resources:
        1. https://fastapi.tiangolo.com/advanced/events/#lifespan-event
    """
    log.debug("Execute FastAPI lifespan event handler.")

    await on_startup(app)
    yield
    await on_shutdown()


def get_application() -> FastAPI:
    """
    Initialize FastAPI application.

    Returns:
       FastAPI: Application object instance.
    """
    log.debug("Initialize FastAPI application node.")

    settings = ApplicationSettings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url=settings.DOCS_URL,
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "*",
        ],  # Add your frontend URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(root_router)
    app.include_router(api_router_v1)

    return app
