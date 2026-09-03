"""
app/infrastructure/github/blobs_client.py
Client for fetching raw file contents from GitHub.
"""

from __future__ import annotations

from app.core.constants import GITHUB_ACCEPT_RAW
from app.infrastructure.github.github_client import get_github_client


async def fetch_blob_content(
    owner: str,
    repo: str,
    file_sha: str,
    github_token: str | None = None,
) -> bytes:
    """
    Fetch the raw content of a file blob from GitHub.
    Uses the vnd.github.v3.raw accept header.
    
    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        file_sha: The SHA of the Git blob.
        github_token: Optional per-repo GitHub PAT.
        
    Returns:
        The raw bytes of the file content.
    """
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/git/blobs/{file_sha}"
    
    response = await client.request(
        "GET", 
        endpoint, 
        custom_headers={"Accept": GITHUB_ACCEPT_RAW},
        github_token=github_token
    )
    
    return response.content
