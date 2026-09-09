"""
app/modules/embedding/providers/jina_provider.py
Embedding provider for Jina AI (jina-embeddings-v3).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any
import httpx

from app.config import get_settings
from app.core.exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingError,
    RateLimitError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class JinaProvider:
    """
    Client for the Jina AI Embeddings API (jina-embeddings-v3).
    Used to generate 1024-dimensional normalized vectors for code chunks and search queries.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = getattr(self.settings, "jina_api_url", "https://api.jina.ai/v1/embeddings")
        self.model = getattr(self.settings, "jina_embedding_model", "jina-embeddings-v3")
        self.max_retries = getattr(self.settings, "jina_max_retries", 5)
        self.dimension = getattr(self.settings, "embedding_dimension", 1024)

        if not self.settings.jina_api_key:
            logger.warning("jina_api_key_missing")

    async def generate_embeddings(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of strings using Jina AI embeddings.

        Args:
            texts: A list of strings to embed.
            input_type: Either 'document' (chunks) or 'query' (search queries).

        Returns:
            A list of float lists, representing the 1024-dim normalized vector embeddings.

        Raises:
            EmbeddingAuthenticationError: If API key is missing or invalid (401).
            EmbeddingError: If non-retryable error occurs or retries are exhausted.
        """
        if not texts:
            return []

        if not self.settings.jina_api_key:
            logger.error("jina_api_key_not_configured")
            raise EmbeddingAuthenticationError("JINA_API_KEY is not configured in settings.")

        # Map input_type to Jina task
        # 'retrieval.passage' for code chunks, 'retrieval.query' for search queries
        task = "retrieval.passage" if input_type == "document" else "retrieval.query"

        headers = {
            "Authorization": f"Bearer {self.settings.jina_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "task": task,
            "dimensions": self.dimension,
            "normalized": True,
            "input": texts,
        }

        logger.info(
            "jina_api_call_started",
            batch_size=len(texts),
            model=self.model,
            task=task,
            dimension=self.dimension,
        )

        backoff = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=httpx.Timeout(30.0),
                    )

                status_code = response.status_code

                # 1. Successful response
                if status_code == 200:
                    data = response.json()
                    # Jina returns list sorted by index in 'data'
                    items = data.get("data", [])
                    items_sorted = sorted(items, key=lambda x: x.get("index", 0))
                    embeddings = [item["embedding"] for item in items_sorted]

                    logger.info(
                        "jina_api_call_success",
                        received_embeddings=len(embeddings),
                        model=self.model,
                        task=task,
                    )
                    return embeddings

                # 2. Authentication failure (401 Unauthorized) - Non-retryable
                if status_code == 401:
                    logger.error("jina_api_auth_failed", status_code=401)
                    raise EmbeddingAuthenticationError(
                        "Jina API returned 401 Unauthorized. Please check your JINA_API_KEY."
                    )

                # 3. Client bad request / validation error (400, 422) - Non-retryable
                if status_code in (400, 422):
                    err_text = response.text
                    logger.error("jina_api_client_error", status_code=status_code, error=err_text)
                    raise EmbeddingError(
                        f"Jina API returned non-retryable HTTP {status_code}: {err_text}"
                    )

                # 4. Rate limit (429) - Retry with exponential backoff + jitter
                if status_code == 429:
                    retry_after_hdr = response.headers.get("Retry-After")
                    if retry_after_hdr:
                        try:
                            delay = float(retry_after_hdr)
                        except ValueError:
                            delay = min(2.0 * (2 ** (attempt - 1)) + random.uniform(0.1, 1.0), 30.0)
                    else:
                        delay = min(2.0 * (2 ** (attempt - 1)) + random.uniform(0.1, 1.0), 30.0)

                    logger.warning(
                        "jina_api_rate_limit",
                        attempt=attempt,
                        delay=round(delay, 2),
                        max_retries=self.max_retries,
                    )
                    if attempt >= self.max_retries:
                        raise RateLimitError("jina", retry_after=delay)
                    await asyncio.sleep(delay)
                    continue

                # 5. Server errors (5xx) - Retry
                if 500 <= status_code < 600:
                    logger.warning(
                        "jina_api_server_error",
                        status_code=status_code,
                        attempt=attempt,
                        delay=backoff,
                    )
                    if attempt == self.max_retries:
                        raise EmbeddingError(
                            f"Jina API returned server error HTTP {status_code} after {self.max_retries} attempts."
                        )
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue

                # Any other unexpected status code
                response.raise_for_status()

            except (httpx.TimeoutException, httpx.NetworkError) as net_exc:
                logger.warning(
                    "jina_api_network_error",
                    attempt=attempt,
                    delay=backoff,
                    error=str(net_exc),
                )
                if attempt == self.max_retries:
                    raise EmbeddingError(
                        f"Network error calling Jina API after {self.max_retries} attempts: {net_exc}"
                    ) from net_exc
                await asyncio.sleep(backoff)
                backoff *= 2.0

            except (EmbeddingAuthenticationError, EmbeddingError, RateLimitError):
                raise

            except Exception as unk_exc:
                logger.error("jina_api_unexpected_error", exc_info=unk_exc)
                raise EmbeddingError(f"Unexpected error generating embeddings: {unk_exc}") from unk_exc

        raise EmbeddingError(f"Failed to generate embeddings after {self.max_retries} attempts.")
