"""Application errors with stable machine-readable codes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An error that is safe to show to the user (no stack traces, no secrets)."""

    def __init__(self, status_code: int, code: str, message: str, details: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def not_found(code: str, message: str) -> AppError:
    return AppError(404, code, message)


def bad_request(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(400, code, message, details)


def unprocessable(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(422, code, message, details)
