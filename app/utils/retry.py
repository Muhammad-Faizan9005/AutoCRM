"""Retry decorator with exponential backoff for resilient database operations."""

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar, Coroutine

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_retries: int = 3,
    initial_delay_ms: int = 100,
    backoff_multiplier: float = 2.5,
    max_delay_ms: int = 5000,
):
    """
    Decorator for retrying operations with exponential backoff.
    
    Useful for handling transient database connection failures, timeouts, etc.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay_ms: Initial delay between retries in milliseconds (default: 100)
        backoff_multiplier: Multiplier for exponential backoff (default: 2.5)
        max_delay_ms: Maximum delay between retries in milliseconds (default: 5000)
    
    Example:
        @retry(max_retries=3, initial_delay_ms=100)
        async def fetch_user(user_id: str):
            # Query that might fail transiently
            return db.query(User).filter(User.id == user_id).first()
    """
    
    def decorator(func: F) -> F:
        # Handle both async and sync functions
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                delay_ms = initial_delay_ms
                last_exception = None
                
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        
                        # If this was the last attempt, re-raise the exception
                        if attempt == max_retries:
                            logger.error(
                                f"Failed after {max_retries + 1} attempts: {func.__name__}",
                                exc_info=True
                            )
                            raise
                        
                        # Log the retry attempt
                        logger.warning(
                            f"Retry attempt {attempt + 1}/{max_retries + 1} for {func.__name__} "
                            f"after {delay_ms}ms (error: {type(e).__name__})"
                        )
                        
                        # Wait before retrying
                        await asyncio.sleep(delay_ms / 1000)
                        
                        # Calculate next delay with exponential backoff
                        delay_ms = min(
                            int(delay_ms * backoff_multiplier),
                            max_delay_ms
                        )
                
                # This shouldn't be reached, but just in case
                raise last_exception or Exception(f"Retry exhausted for {func.__name__}")
            
            return async_wrapper  # type: ignore
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                delay_ms = initial_delay_ms
                last_exception = None
                
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        
                        # If this was the last attempt, re-raise the exception
                        if attempt == max_retries:
                            logger.error(
                                f"Failed after {max_retries + 1} attempts: {func.__name__}",
                                exc_info=True
                            )
                            raise
                        
                        # Log the retry attempt
                        logger.warning(
                            f"Retry attempt {attempt + 1}/{max_retries + 1} for {func.__name__} "
                            f"after {delay_ms}ms (error: {type(e).__name__})"
                        )
                        
                        # Wait before retrying
                        delay_seconds = delay_ms / 1000
                        import time
                        time.sleep(delay_seconds)
                        
                        # Calculate next delay with exponential backoff
                        delay_ms = min(
                            int(delay_ms * backoff_multiplier),
                            max_delay_ms
                        )
                
                # This shouldn't be reached, but just in case
                raise last_exception or Exception(f"Retry exhausted for {func.__name__}")
            
            return sync_wrapper  # type: ignore
    
    return decorator
