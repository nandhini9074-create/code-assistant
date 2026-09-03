"""
app/api/router.py
Main API router aggregating all v1 routes.
"""

from fastapi import APIRouter

from app.api.v1.health_routes import router as health_router
from app.api.v1.ingestion_routes import router as ingestion_router
from app.api.v1.jobs_routes import router as jobs_router
from app.api.v1.repositories_routes import router as repositories_router
from app.api.v1.search_routes import router as search_router
from app.api.v1.webhook_routes import router as webhook_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(repositories_router)
api_router.include_router(ingestion_router)
api_router.include_router(search_router)
api_router.include_router(jobs_router)
api_router.include_router(webhook_router)
