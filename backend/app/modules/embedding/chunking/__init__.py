"""
app/modules/embedding/chunking/__init__.py
Code chunking module.
"""

from app.modules.embedding.chunking.ast_chunker import chunk_ast
from app.modules.embedding.chunking.text_chunker import chunk_text

__all__ = [
    "chunk_ast",
    "chunk_text",
]
