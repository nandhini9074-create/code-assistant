
"""
app/main.py
Main entry point for the FastAPI application.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.infrastructure.database.session import init_db, close_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifecycle events.

    Initializes PostgreSQL on application startup and
    closes the database connection on application shutdown.
    """
    configure_logging(json_logs=True)
    logger.info("app_startup")

    # Initialize PostgreSQL database engine and session factory.
    await init_db()

    logger.info("app_ready")

    try:
        yield
    finally:
        # Close PostgreSQL connections on application shutdown.
        await close_db()
        logger.info("app_shutdown")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Code Explorer API",
        version="1.0.0",
        docs_url="/docs" if settings.app_env == "development" else None,
        redoc_url="/redoc" if settings.app_env == "development" else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register custom request context/logging middleware and exception handlers
    register_middleware(app)

    # Register API routers
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict:
        """
        Basic health check endpoint for load balancers.
        """
        return {
            "status": "ok",
            "environment": settings.app_env,
        }

    return app


# Create the global app instance for Uvicorn
app = create_app()