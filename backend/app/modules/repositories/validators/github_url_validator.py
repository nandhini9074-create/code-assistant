"""
app/modules/repositories/validators/github_url_validator.py
URL validator for GitHub repositories.
"""

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.core.security import parse_github_url

logger = get_logger(__name__)


def validate_and_parse_github_url(url: str) -> tuple[str, str]:
    """
    Validates a GitHub URL and extracts the owner and repo name.
    
    Args:
        url: The GitHub URL to parse.
        
    Returns:
        A tuple of (owner, repo_name).
        
    Raises:
        ValidationError: If the URL is invalid.
    """
    try:
        # We reuse the core security parsing logic which already implements regex validation
        owner, repo = parse_github_url(url)
        logger.debug("github_url_parsed_successfully", url=url, owner=owner, repo=repo)
        return owner, repo
    except Exception as exc:
        logger.warning("github_url_parse_failed", url=url, error=str(exc))
        raise ValidationError(f"Invalid GitHub URL: {str(exc)}") from exc
