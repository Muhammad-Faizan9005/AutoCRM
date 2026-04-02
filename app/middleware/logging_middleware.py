from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Request


logger = logging.getLogger("autocrm.http")


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
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
        },
    )

    return response
