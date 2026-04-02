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
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _prune(self, bucket: deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            self._prune(bucket, now, window_seconds)

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, math.ceil((oldest + window_seconds) - now))
                return RateLimitResult(allowed=False, remaining=0, retry_after_seconds=retry_after)

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return RateLimitResult(allowed=True, remaining=remaining, retry_after_seconds=0)


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
    window_seconds = 60
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{path}"

    result = _limiter.check(key, limit=limit, window_seconds=window_seconds)
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
