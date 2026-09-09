"""
app/modules/embedding/providers/jina_provider.py

Embedding provider for Jina AI.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import get_settings
from app.core.exceptions import EmbeddingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class JinaProvider:
    """
    Client for the Jina AI Embeddings API.

    Model:
        jina-embeddings-v3

    Dimension:
        1024
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        self.api_url = "https://api.jina.ai/v1/embeddings"
        self.model = "jina-embeddings-v3"

        if not self.settings.jina_api_key:
            logger.warning("jina_api_key_missing")

    async def generate_embeddings(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of strings.

        Args:
            texts:
                Texts to embed.

            input_type:
                "document" for repository code.
                "query" for user search queries.

        Returns:
            List of 1024-dimensional embedding vectors.

        Raises:
            EmbeddingError:
                If the Jina API request fails.
        """

        if not texts:
            return []

        if input_type not in {"document", "query"}:
            raise ValueError(
                "input_type must be either 'document' or 'query'."
            )

        headers = {
            "Authorization": f"Bearer {self.settings.jina_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": texts,
        }

        for attempt in range(
            1,
            self.settings.jina_max_retries + 1,
        ):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=httpx.Timeout(30.0),
                    )

                if response.status_code == 429:
                    if attempt < self.settings.jina_max_retries:
                        retry_after = float(
                            response.headers.get(
                                "retry-after",
                                2 * attempt,
                            )
                        )

                        logger.warning(
                            "jina_rate_limited_retrying",
                            attempt=attempt,
                            retry_after=retry_after,
                        )

                        await asyncio.sleep(retry_after)
                        continue

                response.raise_for_status()

                data = response.json()

                embeddings = [
                    item["embedding"]
                    for item in data["data"]
                ]

                # Validate dimension.
                for embedding in embeddings:
                    if len(embedding) != 1024:
                        raise EmbeddingError(
                            "Jina returned an embedding with "
                            f"{len(embedding)} dimensions; "
                            "expected 1024."
                        )

                logger.info(
                    "jina_embeddings_generated",
                    count=len(embeddings),
                    dimension=1024,
                    input_type=input_type,
                )

                return embeddings

            except httpx.RequestError as exc:

                if attempt < self.settings.jina_max_retries:
                    await asyncio.sleep(
                        1.0 * attempt
                    )
                    continue

                logger.error(
                    "jina_api_request_failed",
                    exc_info=exc,
                )

                raise EmbeddingError(
                    f"Network error calling Jina API: {exc}"
                ) from exc

            except httpx.HTTPStatusError as exc:

                if (
                    exc.response.status_code == 429
                    and attempt < self.settings.jina_max_retries
                ):
                    await asyncio.sleep(
                        2.0 * attempt
                    )
                    continue

                logger.error(
                    "jina_api_http_error",
                    status_code=exc.response.status_code,
                    text=exc.response.text,
                )

                raise EmbeddingError(
                    "Jina API returned HTTP "
                    f"{exc.response.status_code}: "
                    f"{exc.response.text}"
                ) from exc

            except EmbeddingError:
                raise

            except Exception as exc:

                logger.error(
                    "jina_api_unexpected_error",
                    exc_info=exc,
                )

                raise EmbeddingError(
                    "Unexpected error generating embeddings: "
                    f"{exc}"
                ) from exc

        raise EmbeddingError(
            "Failed to generate embeddings after max retries."
        )