from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "APP_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        if code:
            self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class InvalidInputError(AppError):
    code = "INVALID_INPUT"
    status_code = 400


class RouteViolationError(AppError):
    code = "ROUTE_VIOLATION"
    status_code = 422
