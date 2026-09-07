"""
app/modules/embedding/providers/__init__.py
Embedding provider registry.
"""

from app.modules.embedding.providers.jina_provider import JinaProvider

__all__ = [
    "JinaProvider",
]
