"Domain errors and the single error envelope returned for every failure."

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Internal server error"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do that"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource already exists"


class UnprocessableError(AppError):
    status_code = 422
    code = "unprocessable"
    message = "The request could not be processed"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Service temporarily unavailable"


def _envelope(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    headers: dict[str, str] = {}
    if status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id or request_id_var.get(),
            "details": details or [],
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers or None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the submitted value: it may be a password.
        details = [
            {"field": ".".join(str(part) for part in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _envelope(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}
        return _envelope(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        request_id = str(request.scope.get("request_id", "-"))
        return _envelope(500, "internal_error", "Internal server error", request_id=request_id)
