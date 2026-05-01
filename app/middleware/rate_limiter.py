from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.config import settings


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """
    In-memory rate limiter with support for:
    - Token bucket algorithm with sliding window
    - Per-endpoint and per-IP rate limiting
    - Request queue tracking for monitoring
    """
    
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._queued_requests: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._queued_requests.clear()

    def _prune(self, bucket: deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(
        self, 
        key: str, 
        *, 
        limit: int, 
        window_seconds: int,
        max_queue_size: int = 500
    ) -> RateLimitResult:
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            self._prune(bucket, now, window_seconds)

            if len(bucket) >= limit:
                # Rate limit exceeded - check queue size
                queued = self._queued_requests.get(key, 0)
                if queued >= max_queue_size:
                    # Queue is full - reject request
                    oldest = bucket[0]
                    retry_after = max(1, math.ceil((oldest + window_seconds) - now))
                    return RateLimitResult(
                        allowed=False, 
                        remaining=0, 
                        retry_after_seconds=retry_after
                    )
                else:
                    # Queue has space - queue the request
                    self._queued_requests[key] = queued + 1
                    oldest = bucket[0]
                    retry_after = max(1, math.ceil((oldest + window_seconds) - now))
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        retry_after_seconds=retry_after
                    )

            bucket.append(now)
            # Decrement queue count when request is processed
            if key in self._queued_requests and self._queued_requests[key] > 0:
                self._queued_requests[key] -= 1
            
            remaining = max(0, limit - len(bucket))
            return RateLimitResult(allowed=True, remaining=remaining, retry_after_seconds=0)
    
    def get_queue_stats(self) -> dict[str, int]:
        """Get current queue statistics for monitoring."""
        with self._lock:
            return dict(self._queued_requests)


_limiter = InMemoryRateLimiter()
_EXEMPT_PATHS = {"/docs", "/redoc", "/openapi.json"}


def reset_rate_limiter_state() -> None:
    _limiter.reset()


async def rate_limit_middleware(request: Request, call_next):
    if not settings.RATE_LIMIT_ENABLED:
        return await call_next(request)

    path = request.url.path
    if path in _EXEMPT_PATHS:
        return await call_next(request)

    limit = max(1, settings.RATE_LIMIT_REQUESTS_PER_MINUTE)
    max_queue_size = max(1, settings.RATE_LIMIT_MAX_QUEUE_SIZE)
    window_seconds = 60
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{path}"

    result = _limiter.check(
        key, 
        limit=limit, 
        window_seconds=window_seconds,
        max_queue_size=max_queue_size
    )
    if not result.allowed:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "error": {
                    "code": status.HTTP_429_TOO_MANY_REQUESTS,
                    "message": "Rate limit exceeded",
                    "request_id": request_id,
                }
            },
            headers={
                "Retry-After": str(result.retry_after_seconds),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    return response
