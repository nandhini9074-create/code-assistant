"""
tests/unit/test_jina_provider.py
Unit tests for JinaProvider and Jina embeddings integration.
"""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.core.exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingError,
    RateLimitError,
)
from app.modules.embedding.providers.jina_provider import JinaProvider
from app.infrastructure.qdrant.collection_manager import ensure_collection_exists
from qdrant_client.http import models as qmodels


@pytest.fixture
def jina_provider():
    with patch("app.modules.embedding.providers.jina_provider.get_settings") as mock_settings:
        mock_settings.return_value.jina_api_key = "test_jina_key_12345"
        mock_settings.return_value.jina_api_url = "https://api.jina.ai/v1/embeddings"
        mock_settings.return_value.jina_embedding_model = "jina-embeddings-v3"
        mock_settings.return_value.jina_max_retries = 3
        mock_settings.return_value.embedding_dimension = 1024
        yield JinaProvider()


@pytest.mark.asyncio
async def test_successful_jina_embedding_generation_1024_dim(jina_provider):
    """Test generating 1024-dimensional normalized embeddings."""
    mock_response_data = {
        "data": [
            {"index": 0, "embedding": [0.01] * 1024},
            {"index": 1, "embedding": [0.02] * 1024},
        ]
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_response_data,
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        embeddings = await jina_provider.generate_embeddings(
            ["def foo(): pass", "class Bar: pass"],
            input_type="document",
        )

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 1024
        assert len(embeddings[1]) == 1024

        # Verify request parameters
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["model"] == "jina-embeddings-v3"
        assert payload["task"] == "retrieval.passage"
        assert payload["dimensions"] == 1024
        assert payload["normalized"] is True
        assert payload["input"] == ["def foo(): pass", "class Bar: pass"]
        assert "Bearer test_jina_key_12345" in call_kwargs["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_query_task_mapping(jina_provider):
    """Test that input_type='query' maps to task='retrieval.query'."""
    mock_resp = httpx.Response(
        status_code=200,
        json={"data": [{"index": 0, "embedding": [0.05] * 1024}]},
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        embeddings = await jina_provider.generate_embeddings(
            ["how to implement auth"],
            input_type="query",
        )

        assert len(embeddings) == 1
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["task"] == "retrieval.query"


@pytest.mark.asyncio
async def test_401_unauthorized_handling(jina_provider):
    """Test that 401 Unauthorized raises EmbeddingAuthenticationError immediately without retrying."""
    mock_resp = httpx.Response(
        status_code=401,
        json={"error": "Invalid API key"},
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(EmbeddingAuthenticationError) as exc_info:
            await jina_provider.generate_embeddings(["test code"])

        assert "401 Unauthorized" in str(exc_info.value)
        # 401 should not retry 3 times
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_429_rate_limit_retry_and_backoff(jina_provider):
    """Test that 429 rate limit triggers retries with backoff."""
    resp_429 = httpx.Response(
        status_code=429,
        headers={"Retry-After": "0.01"},
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )
    resp_200 = httpx.Response(
        status_code=200,
        json={"data": [{"index": 0, "embedding": [0.1] * 1024}]},
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [resp_429, resp_200]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            embeddings = await jina_provider.generate_embeddings(["test code"])

            assert len(embeddings) == 1
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.01)


@pytest.mark.asyncio
async def test_5xx_server_error_retry(jina_provider):
    """Test that 500 server error triggers retries and eventually raises EmbeddingError if all fail."""
    resp_500 = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", "https://api.jina.ai/v1/embeddings"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = resp_500

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(EmbeddingError) as exc_info:
                await jina_provider.generate_embeddings(["test code"])

            assert "server error HTTP 500" in str(exc_info.value)
            assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_qdrant_dimension_validation():
    """Test Qdrant collection validation for 1024-dim and cosine distance."""
    mock_client = AsyncMock()

    # Case 1: Collection exists with correct 1024 size and Cosine
    mock_coll_info = AsyncMock()
    mock_coll_info.config.params.vectors = qmodels.VectorParams(
        size=1024,
        distance=qmodels.Distance.COSINE,
    )
    mock_coll_desc = AsyncMock()
    mock_coll_desc.name = "repo_test"
    mock_collections_resp = AsyncMock()
    mock_collections_resp.collections = [mock_coll_desc]
    mock_client.get_collections.return_value = mock_collections_resp
    mock_client.get_collection.return_value = mock_coll_info

    with patch("app.infrastructure.qdrant.collection_manager.get_qdrant_client", return_value=mock_client):
        await ensure_collection_exists("repo_test", vector_size=1024)
        mock_client.create_collection.assert_not_called()

    # Case 2: Dimension mismatch (e.g. 1536 or 768)
    mock_coll_info.config.params.vectors = qmodels.VectorParams(
        size=768,
        distance=qmodels.Distance.COSINE,
    )
    with patch("app.infrastructure.qdrant.collection_manager.get_qdrant_client", return_value=mock_client):
        with pytest.raises(ValueError) as exc_info:
            await ensure_collection_exists("repo_test", vector_size=1024)
        assert "dimension mismatch" in str(exc_info.value)
