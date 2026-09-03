"""
app/shared/types/repo_types.py
Type aliases for repository-related entities.
"""

from typing import TypeAlias
from uuid import UUID

RepoId: TypeAlias = UUID
JobId: TypeAlias = UUID
ChunkId: TypeAlias = UUID
PointId: TypeAlias = str  # Qdrant point IDs are strings (UUIDv5)
