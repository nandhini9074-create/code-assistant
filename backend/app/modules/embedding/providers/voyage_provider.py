"""
app/modules/embedding/providers/voyage_provider.py
Embedding provider for Voyage AI.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.core.exceptions import EmbeddingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class VoyageProvider:
    """
    Client for the Voyage AI Embeddings API.
    Used to generate 1024-dimensional vectors for code chunks.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = "https://api.voyageai.com/v1/embeddings"
        
        if not self.settings.voyage_api_key:
            logger.warning("voyage_api_key_missing")

    async def generate_embeddings(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of strings.
        
        Args:
            texts: A list of strings to embed.
            input_type: Either 'document' (for chunks) or 'query' (for search queries).
            
        Returns:
            A list of float lists, representing the vector embeddings.
            
        Raises:
            EmbeddingError: If the API request fails.
        """
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.settings.voyage_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "input": texts,
            "model": self.settings.voyage_embedding_model,
            "input_type": input_type,
        }

        for attempt in range(1, self.settings.voyage_max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=httpx.Timeout(30.0),
                    )
                    
                    if response.status_code == 429:
                        if attempt < self.settings.voyage_max_retries:
                            retry_after = float(response.headers.get("retry-after", 2 * attempt))
                            logger.warning(
                                "voyage_rate_limited_retrying",
                                attempt=attempt,
                                retry_after=retry_after,
                            )
                            import asyncio
                            await asyncio.sleep(retry_after)
                            continue

                    response.raise_for_status()
                    data = response.json()
                    
                    # The response data["data"] is a list of objects with an "embedding" field
                    embeddings = [item["embedding"] for item in data["data"]]
                    return embeddings
                    
            except httpx.RequestError as exc:
                if attempt < self.settings.voyage_max_retries:
                    import asyncio
                    await asyncio.sleep(1.0 * attempt)
                    continue
                logger.error("voyage_api_request_failed", exc_info=exc)
                raise EmbeddingError(f"Network error calling Voyage API: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < self.settings.voyage_max_retries:
                    import asyncio
                    await asyncio.sleep(2.0 * attempt)
                    continue
                logger.error("voyage_api_http_error", status_code=exc.response.status_code, text=exc.response.text)
                raise EmbeddingError(f"Voyage API returned HTTP {exc.response.status_code}: {exc.response.text}") from exc
            except Exception as exc:
                logger.error("voyage_api_unexpected_error", exc_info=exc)
                raise EmbeddingError(f"Unexpected error generating embeddings: {exc}") from exc
        
        raise EmbeddingError("Failed to generate embeddings after max retries")

