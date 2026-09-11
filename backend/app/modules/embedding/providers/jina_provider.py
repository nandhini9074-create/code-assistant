"""
app/modules/embedding/providers/jina_provider.py

Embedding provider for Jina AI (jina-embeddings-v3).

Generates 1024-dimensional normalized vectors for:
- Code chunks during ingestion  (input_type="document" → task="retrieval.passage")
- User search queries           (input_type="query"    → task="retrieval.query")
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

    Model   : jina-embeddings-v3
    Dimension: 1024 (normalized)

    Reads all tuning parameters from Settings so they can be
    overridden via environment variables without code changes.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = getattr(
            self.settings, "jina_api_url", "https://api.jina.ai/v1/embeddings"
        )
        self.model = getattr(
            self.settings, "jina_embedding_model", "jina-embeddings-v3"
        )
        self.max_retries = getattr(self.settings, "jina_max_retries", 6)
        self.dimension = getattr(self.settings, "embedding_dimension", 1024)

        if not self.settings.jina_api_key:
            logger.warning("jina_api_key_missing")

    async def generate_embeddings(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of strings using Jina AI.

        Args:
            texts: A list of strings to embed.
            input_type: Either 'document' (chunks) or 'query' (search queries).

        Returns:
            A list of float lists — 1024-dim normalized vector embeddings.

        Raises:
            EmbeddingAuthenticationError: If the API key is missing or rejected (401).
            RateLimitError: If the API rate-limits and retries are exhausted.
            EmbeddingError: For any other non-retryable or exhausted-retry failure.
        """
        if not texts:
            return []

        if input_type not in {"document", "query"}:
            raise ValueError("input_type must be either 'document' or 'query'.")

        if not self.settings.jina_api_key:
            logger.error("jina_api_key_not_configured")
            raise EmbeddingAuthenticationError(
                "JINA_API_KEY is not configured in settings."
            )

        # Map input_type → Jina task name
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

                # ── 200 OK ───────────────────────────────────────────────
                if status_code == 200:
                    data = response.json()
                    items = data.get("data", [])
                    items_sorted = sorted(items, key=lambda x: x.get("index", 0))
                    embeddings = [item["embedding"] for item in items_sorted]

                    # Validate dimension
                    for emb in embeddings:
                        if len(emb) != self.dimension:
                            raise EmbeddingError(
                                f"Jina returned embedding with {len(emb)} dimensions; "
                                f"expected {self.dimension}."
                            )

                    logger.info(
                        "jina_api_call_success",
                        received_embeddings=len(embeddings),
                        model=self.model,
                        task=task,
                    )
                    return embeddings

                # ── 401 Unauthorized — Non-retryable ─────────────────────
                if status_code == 401:
                    logger.error("jina_api_auth_failed", status_code=401)
                    raise EmbeddingAuthenticationError(
                        "Jina API returned 401 Unauthorized. Check your JINA_API_KEY."
                    )

                # ── 400/422 Client Error — Non-retryable ──────────────────
                if status_code in (400, 422):
                    err_text = response.text
                    logger.error(
                        "jina_api_client_error",
                        status_code=status_code,
                        error=err_text,
                    )
                    raise EmbeddingError(
                        f"Jina API returned non-retryable HTTP {status_code}: {err_text}"
                    )

                # ── 429 Rate Limit — Retry with backoff + jitter ──────────
                if status_code == 429:
                    retry_after_hdr = response.headers.get("Retry-After")
                    if retry_after_hdr:
                        try:
                            delay = float(retry_after_hdr)
                        except ValueError:
                            delay = min(
                                2.0 * (2 ** (attempt - 1)) + random.uniform(0.1, 1.0),
                                30.0,
                            )
                    else:
                        delay = min(
                            2.0 * (2 ** (attempt - 1)) + random.uniform(0.1, 1.0),
                            30.0,
                        )

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

                # ── 5xx Server Error — Retry with exponential backoff ─────
                if 500 <= status_code < 600:
                    logger.warning(
                        "jina_api_server_error",
                        status_code=status_code,
                        attempt=attempt,
                        delay=backoff,
                    )
                    if attempt == self.max_retries:
                        raise EmbeddingError(
                            f"Jina API returned server error HTTP {status_code} "
                            f"after {self.max_retries} attempts."
                        )
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue

                # ── Any other unexpected status code ──────────────────────
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
                raise EmbeddingError(
                    f"Unexpected error generating embeddings: {unk_exc}"
                ) from unk_exc

        raise EmbeddingError(
            f"Failed to generate embeddings after {self.max_retries} attempts."
        )
