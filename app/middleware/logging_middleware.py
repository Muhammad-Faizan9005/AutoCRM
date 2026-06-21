from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Request


logger = logging.getLogger("autocrm.http")
SLOW_REQUEST_THRESHOLD_MS = 1000


async def logging_middleware(request: Request, call_next):
    start = time.perf_counter()

    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    client_ip = request.client.host if request.client else "unknown"

    logger.info(
        "request_started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": client_ip,
        },
    )

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(duration_ms)

    log_level = logging.WARNING if duration_ms >= SLOW_REQUEST_THRESHOLD_MS else logging.INFO
    logger.log(
        log_level,
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "route": route_path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
            "slow_request": duration_ms >= SLOW_REQUEST_THRESHOLD_MS,
        },
    )

    return response
