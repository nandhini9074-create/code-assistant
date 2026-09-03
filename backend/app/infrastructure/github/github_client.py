"""
app/infrastructure/github/github_client.py
Base async HTTP client for the GitHub API.

Provides automatic rate-limit handling, retry backoff, and 
proper authorization headers.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings
from app.core.constants import (
    GITHUB_ACCEPT_JSON,
    GITHUB_API_VERSION,
    GITHUB_MAX_RETRIES,
    GITHUB_RETRY_BASE_DELAY,
)
from app.core.exceptions import GitHubNotFoundError, GitHubRateLimitError, GitHubAPIError
from app.core.logging import get_logger

logger = get_logger(__name__)


class GitHubClient:
    """
    Base HTTP client for GitHub REST API calls.
    Handles retries, rate limits, and common error mapping.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.github_api_base_url
        
        headers = {
            "Accept": GITHUB_ACCEPT_JSON,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
            
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        custom_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Execute an HTTP request against the GitHub API with retry logic.
        """
        url = endpoint.lstrip("/")
        
        req_headers = kwargs.pop("headers", {})
        if custom_headers:
            req_headers.update(custom_headers)
            
        for attempt in range(1, GITHUB_MAX_RETRIES + 1):
            try:
                response = await self.client.request(
                    method,
                    url,
                    headers=req_headers if req_headers else None,
                    **kwargs,
                )
                
                # Check for rate limits first
                if response.status_code == 403 and "rate limit exceeded" in response.text.lower():
                    reset_time = response.headers.get("x-ratelimit-reset")
                    logger.warning("github_rate_limit_hit", endpoint=endpoint, reset_time=reset_time)
                    raise GitHubRateLimitError("GitHub API rate limit exceeded.", endpoint=endpoint)
                    
                if response.status_code == 404:
                    raise GitHubNotFoundError(
                        f"Resource not found: {endpoint}",
                        status_code=404,
                        endpoint=endpoint,
                    )
                    
                response.raise_for_status()
                return response

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == GITHUB_MAX_RETRIES:
                    status_code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
                    logger.error("github_api_failed", endpoint=endpoint, attempt=attempt, exc_info=exc)
                    raise GitHubAPIError(
                        f"GitHub API request failed: {exc}",
                        status_code=status_code,
                        endpoint=endpoint,
                    ) from exc
                
                delay = GITHUB_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("github_api_retry", endpoint=endpoint, attempt=attempt, delay=delay)
                await asyncio.sleep(delay)
                
        # Fallback (should be unreachable due to max retries check inside loop)
        raise GitHubAPIError("Maximum retries exceeded", endpoint=endpoint)


# Module-level singleton pattern for shared connection pool
_client_instance: GitHubClient | None = None

def get_github_client() -> GitHubClient:
    """Get or create the singleton GitHub client."""
    global _client_instance
    if _client_instance is None:
        _client_instance = GitHubClient()
    return _client_instance

async def close_github_client() -> None:
    """Close the singleton GitHub client on shutdown."""
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
