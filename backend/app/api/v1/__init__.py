"""
app/api/v1/__init__.py
API v1 module — re-exports api_router for use by main.py.
"""

from app.api.router import api_router

__all__ = ["api_router"]
