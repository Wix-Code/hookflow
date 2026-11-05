from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_STATUS_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


class Conflict(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(409, code, message)


class NotFound(AppError):
    def __init__(self, code: str = "not_found", message: str = "Resource not found") -> None:
        super().__init__(404, code, message)


class Forbidden(AppError):
    def __init__(
        self, code: str = "insufficient_role", message: str = "You do not have permission to do this"
    ) -> None:
        super().__init__(403, code, message)
        

class Unauthorized(AppError):
    def __init__(self, code: str = "not_authenticated", message: str = "Authentication required") -> None:
        super().__init__(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def error_body(code: str, message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"code": code}
    if errors:
        data["errors"] = errors
    return {"status": "error", "message": message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Request validation failed", errors), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(error_body(code, message), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            error_body("internal_error", "An unexpected error occurred"), status_code=500
        )
        
    