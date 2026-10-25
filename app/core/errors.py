"""Domain errors and their mapping to RFC 9457 problem details responses."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    title = "Bad request"
    type = "about:blank"

    def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.headers = headers


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    title = "Conflict"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Not authenticated"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Forbidden"


def problem(status_code: int, title: str, detail: str | None, request: Request, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id_var.get(),
    }
    body.update(extra)
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        response = problem(exc.status_code, exc.title, exc.detail, request)
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"location": list(error["loc"]), "message": error["msg"], "type": error["type"]} for error in exc.errors()]
        return problem(422, "Validation failed", "The request contains invalid fields.", request, errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = {404: "Not found", 405: "Method not allowed"}.get(exc.status_code, "HTTP error")
        detail = exc.detail if isinstance(exc.detail, str) else None
        return problem(exc.status_code, title, detail, request)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Full details go to the log; the client only gets the request ID to quote in a support request.
        logger.exception("Unhandled error", extra={"path": request.url.path})
        return problem(500, "Internal server error", "An unexpected error occurred.", request)
