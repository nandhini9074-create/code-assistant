"""
app/shared/utils/retry.py
Generic async retry with exponential backoff.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def with_retry(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """
    Execute an async function with exponential backoff retry logic.
    """
    delay = initial_delay
    last_exc: Exception | None = None
    
    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt == max_retries:
                logger.error("retry_failed_final", func=func.__name__, attempt=attempt)
                raise
                
            logger.warning(
                "retry_attempt_failed",
                func=func.__name__,
                attempt=attempt,
                next_delay=delay,
                exc_info=exc,
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor
            
    # Fallback to satisfy type checker, though loop will raise on final attempt
    raise last_exc or Exception("Retry failed without exception")
