"""
app/modules/ingestion/pipeline/embedding_generation.py
Pipeline stage: Embedding generation.
"""

from __future__ import annotations

import math

from app.config import get_settings
from app.core.constants import DEFAULT_EMBEDDING_DIMENSION, EMBEDDING_BATCH_SIZE
from app.core.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingError,
    EmbeddingGenerationError,
)
from app.core.logging import get_logger
from app.modules.embedding.service.embedding_service import generate_embeddings
from app.modules.ingestion.domain.ingestion_domain import ChunkRecord, IngestionContext

logger = get_logger(__name__)


class EmbeddingGenerationStage:
    """
    Stage 9: Generates vector embeddings for all new or modified code chunks.
    Ensures:
      - Only chunks with `chunk.is_new == True` and valid non-empty code are embedded.
      - Chunks are dispatched in configurable batches preserving strict 1-to-1 ordering.
      - Exact match between chunk count and returned vector count.
      - Vector dimensions match the configured embedding dimension.
      - Attaches model and dimension metadata to `chunk.metadata`.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.batch_size = (
            getattr(self.settings, "jina_embedding_batch_size", None)
            or EMBEDDING_BATCH_SIZE
        )
        self.expected_dimension = (
            getattr(self.settings, "embedding_dimension", None)
            or DEFAULT_EMBEDDING_DIMENSION
        )
        self.model_name = getattr(self.settings, "jina_embedding_model", "jina-embeddings-v3")
        self.inter_batch_delay = getattr(
            self.settings, "jina_inter_batch_delay", 2.0
        )

    async def execute(self, context: IngestionContext) -> None:
        """Generates vector embeddings for new chunks."""
        new_chunks: list[ChunkRecord] = []

        # 1. Collect all valid new chunks across all files
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue

            for chunk in file.chunks:
                if not chunk.is_new:
                    continue

                code_text = chunk.code if chunk.code is not None else ""
                if not code_text.strip():
                    logger.warning(
                        "stage_9_empty_chunk_skipped",
                        file_path=chunk.file_path,
                        chunk_hash=chunk.chunk_hash,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                    )
                    continue

                new_chunks.append(chunk)

        if not new_chunks:
            logger.info(
                "stage_9_embedding_generation_skipped",
                reason="No new chunks to embed",
                job_id=context.job_id,
            )
            return

        total_chunks = len(new_chunks)
        total_batches = math.ceil(total_chunks / self.batch_size)
        logger.info(
            "stage_9_embedding_generation_started",
            chunks_to_embed=total_chunks,
            batch_size=self.batch_size,
            total_batches=total_batches,
            model=self.model_name,
            expected_dimension=self.expected_dimension,
            job_id=context.job_id,
        )

        all_embeddings: list[list[float]] = []

        # 2. Process in ordered batches
        for batch_idx in range(total_batches):
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, total_chunks)
            chunk_batch = new_chunks[start_idx:end_idx]
            texts_batch = [c.code for c in chunk_batch]

            logger.info(
                "stage_9_processing_batch",
                batch_number=batch_idx + 1,
                total_batches=total_batches,
                batch_size=len(texts_batch),
                job_id=context.job_id,
            )

            try:
                batch_embeddings = await generate_embeddings(
                    texts=texts_batch,
                    input_type="document",
                )
            except Exception as exc:
                logger.error(
                    "stage_9_embedding_batch_failed",
                    batch_number=batch_idx + 1,
                    total_batches=total_batches,
                    batch_size=len(texts_batch),
                    error=str(exc),
                    job_id=context.job_id,
                    exc_info=exc,
                )
                raise

            # 3. Validate batch response counts
            if len(batch_embeddings) != len(texts_batch):
                err_msg = (
                    f"Embedding count mismatch in batch {batch_idx + 1}/{total_batches}: "
                    f"expected {len(texts_batch)} embeddings, received {len(batch_embeddings)}"
                )
                logger.error("stage_9_count_mismatch", error=err_msg, job_id=context.job_id)
                raise EmbeddingGenerationError(err_msg)

            # 4. Validate vector dimension for every vector in the batch
            for vec_idx, vec in enumerate(batch_embeddings):
                if len(vec) != self.expected_dimension:
                    err_msg = (
                        f"Embedding dimension mismatch at batch {batch_idx + 1}, index {vec_idx}: "
                        f"expected dimension {self.expected_dimension}, received {len(vec)}"
                    )
                    logger.error(
                        "stage_9_dimension_mismatch",
                        error=err_msg,
                        expected=self.expected_dimension,
                        actual=len(vec),
                        job_id=context.job_id,
                    )
                    raise EmbeddingDimensionMismatchError(err_msg)

            all_embeddings.extend(batch_embeddings)

            # Pause between batch dispatches to prevent rate-limit bursts on large repos
            if batch_idx < total_batches - 1 and self.inter_batch_delay > 0:
                import asyncio
                await asyncio.sleep(self.inter_batch_delay)

        # 5. Global count safety check before assignment
        if len(all_embeddings) != total_chunks:
            err_msg = (
                f"Total embedding count mismatch: expected {total_chunks} embeddings for {total_chunks} chunks, "
                f"but collected {len(all_embeddings)}"
            )
            logger.error("stage_9_total_count_mismatch", error=err_msg, job_id=context.job_id)
            raise EmbeddingGenerationError(err_msg)

        # 6. Assign embeddings and model metadata strictly maintaining order
        for chunk, embedding in zip(new_chunks, all_embeddings):
            chunk.embedding = embedding
            if isinstance(chunk.metadata, dict):
                chunk.metadata["embedding_model"] = self.model_name
                chunk.metadata["embedding_dimension"] = self.expected_dimension

        logger.info(
            "stage_9_embedding_generation_completed",
            generated_embeddings_count=len(all_embeddings),
            model=self.model_name,
            dimension=self.expected_dimension,
            job_id=context.job_id,
        )

