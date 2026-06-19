from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.config import settings


_DEFAULT_CSP = "default-src 'none'; frame-ancestors 'none';"
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https:; "
    "font-src 'self' https://cdn.jsdelivr.net data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none';"
)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "1; mode=block",
}


def _csp_for_path(path: str) -> str:
    """Keep strict defaults, but allow docs assets for FastAPI docs pages."""
    if path.startswith("/docs") or path.startswith("/redoc"):
        return _DOCS_CSP
    return _DEFAULT_CSP


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def security_middleware(request: Request, call_next):
    max_size = settings.MAX_REQUEST_SIZE_BYTES
    if request.url.path == "/api/auth/avatar":
        max_size = max(max_size, settings.SUPABASE_MAX_AVATAR_BYTES + 250_000)
    if request.url.path.startswith("/api/calls/") and "/recording" in request.url.path:
        max_size = None

    content_length = request.headers.get("content-length")

    if max_size is not None and content_length and content_length.isdigit() and int(content_length) > max_size:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "success": False,
                "error": {
                    "code": status.HTTP_413_CONTENT_TOO_LARGE,
                    "message": "Request body is too large",
                    "request_id": request_id,
                    "timestamp": _timestamp(),
                },
            },
            headers={"X-Request-ID": request_id},
        )

    response = await call_next(request)

    if settings.SECURITY_HEADERS_ENABLED:
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["Content-Security-Policy"] = _csp_for_path(request.url.path)

    return response
