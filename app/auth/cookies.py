import secrets
from datetime import datetime, timezone

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from app.config import settings

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_TOKEN_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

_AUTH_COOKIE_PATH = "/api/auth"
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register"}


def _cookie_secure() -> bool:
    return not settings.DEBUG


def _cookie_samesite() -> str:
    return "none" if _cookie_secure() else "lax"


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    secure = _cookie_secure()
    csrf_token = secrets.token_urlsafe(32)

    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        httponly=True,
        secure=secure,
        samesite=_cookie_samesite(),
        path="/",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite=_cookie_samesite(),
        path=_AUTH_COOKIE_PATH,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    response.set_cookie(
        CSRF_TOKEN_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite=_cookie_samesite(),
        path="/",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response) -> None:
    secure = _cookie_secure()
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/", secure=secure, samesite=_cookie_samesite())
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path=_AUTH_COOKIE_PATH, secure=secure, samesite=_cookie_samesite())
    response.delete_cookie(CSRF_TOKEN_COOKIE, path="/", secure=secure, samesite=_cookie_samesite())


async def csrf_middleware(request: Request, call_next):
    """Double-submit CSRF check for cookie-authenticated mutating requests."""
    if (
        request.method.upper() in _MUTATING_METHODS
        and request.url.path not in _CSRF_EXEMPT_PATHS
        and (ACCESS_TOKEN_COOKIE in request.cookies or REFRESH_TOKEN_COOKIE in request.cookies)
    ):
        cookie_value = request.cookies.get(CSRF_TOKEN_COOKIE)
        header_value = request.headers.get(CSRF_HEADER)

        if not cookie_value or not header_value or not secrets.compare_digest(cookie_value, header_value):
            request_id = getattr(request.state, "request_id", "unknown")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "error": {
                        "code": status.HTTP_403_FORBIDDEN,
                        "message": "CSRF token missing or invalid",
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                },
                headers={"X-Request-ID": request_id},
            )

    return await call_next(request)
