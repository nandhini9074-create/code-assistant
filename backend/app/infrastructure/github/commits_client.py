"""
app/infrastructure/github/commits_client.py
Client for fetching commit information from GitHub.
"""

from __future__ import annotations

from app.infrastructure.github.github_client import get_github_client


async def fetch_latest_commit_sha(
    owner: str,
    repo: str,
    branch: str = "main",
    github_token: str | None = None,
) -> str:
    """
    Fetch the latest commit SHA for a given branch.
    
    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        branch: The branch to fetch the latest commit for.
        github_token: Optional per-repo GitHub PAT.
        
    Returns:
        The SHA string of the latest commit.
    """
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/commits/{branch}"
    
    response = await client.request("GET", endpoint, github_token=github_token)
    data = response.json()
    
    return data["sha"]
