import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("autocrm.errors")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_error_response(
    *,
    status_code: int,
    error_code: str | int,
    message: str,
    request_id: str,
    details: list[dict] | None = None,
) -> JSONResponse:
    payload = {
        "success": False,
        "error": {
            "code": error_code,
            "message": message,
            "request_id": request_id,
            "timestamp": _now_iso(),
        },
    }
    if details is not None:
        payload["error"]["details"] = details

    return JSONResponse(status_code=status_code, content=payload, headers={"X-Request-ID": request_id})


async def error_handler_middleware(request: Request, call_next):
    """
    Attach request_id to every request/response for traceability.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def setup_exception_handlers(app):
    """
    Setup custom exception handlers for the FastAPI app.
    """
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Handle HTTP exceptions"""
        request_id = getattr(request.state, "request_id", str(uuid4()))
        logger.warning(
            "http_exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": exc.status_code,
            },
        )
        return _build_error_response(
            status_code=exc.status_code,
            error_code=exc.status_code,
            message=str(exc.detail),
            request_id=request_id,
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle validation errors"""
        request_id = getattr(request.state, "request_id", str(uuid4()))

        errors = []
        for error in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(x) for x in error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
            )

        logger.info(
            "validation_error",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            },
        )

        return _build_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            message="Request validation failed",
            request_id=request_id,
            details=errors,
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle all other exceptions"""
        request_id = getattr(request.state, "request_id", str(uuid4()))
        logger.exception(
            "unhandled_exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            },
        )
        return _build_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
            request_id=request_id,
        )
