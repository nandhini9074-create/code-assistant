"""
app/infrastructure/github/trees_client.py
Client for interacting with the GitHub Git Trees API.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.github.github_client import get_github_client


async def fetch_repository_tree(
    owner: str,
    repo: str,
    commit_sha: str,
    github_token: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch the complete Git tree for a specific commit.
    Uses the recursive=1 flag to get all nested files in a single flat list.
    
    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        commit_sha: The commit SHA or branch name to fetch the tree for.
        github_token: Optional per-repo GitHub PAT.
        
    Returns:
        A list of tree nodes (dicts containing path, mode, type, sha, size, url).
    """
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
    
    response = await client.request("GET", endpoint, github_token=github_token)
    data = response.json()
    
    # Return the flat list of items in the tree
    return data.get("tree", [])
