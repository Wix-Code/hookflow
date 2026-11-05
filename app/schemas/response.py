from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Every successful reply has this shape. `data` holds the payload, or null."""

    status: str = "success"
    message: str
    data: T | None = None


class ErrorResponse(BaseModel):
    """Every error reply has this shape. `data.code` is a stable, machine-readable code."""

    status: str = "error"
    message: str
    data: dict[str, Any] | None = None