"""Reads and checks the body of POST /projects/{id}/events.

Why not just declare `body: PublishEventRequest`? FastAPI would read the whole body into memory before any
of our code runs, so a huge upload could not be refused early. Here we count bytes as they arrive and stop at
the limit.
"""

import json
from typing import Annotated

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.event import PublishEventRequest
from app.services.events import MAX_EVENT_BODY_BYTES, IncomingEvent, compute_fingerprint

MAX_JSON_DEPTH = 64  # real payloads rarely go past 10 levels; this only stops abusive nesting


def _too_large() -> AppError:
    return AppError(413, "payload_too_large", "Request body must be 256 KB or smaller")


def _invalid(message: str) -> RequestValidationError:
    return RequestValidationError([{"loc": ("body",), "msg": message, "type": "value_error"}])


def _reject_constant(name: str):
    # Python's json accepts NaN and Infinity, but they are not valid JSON and databases refuse them.
    raise ValueError(f"{name} is not valid JSON")


def _nested_deeper_than(value, limit: int) -> bool:
    """True if objects/arrays are nested more than `limit` levels. Walks with a list, not recursion."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


async def read_incoming_event(request: Request) -> IncomingEvent:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_EVENT_BODY_BYTES:
        raise _too_large()

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_EVENT_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)

    too_deep = _invalid(f"JSON must not be nested more than {MAX_JSON_DEPTH} levels deep")
    try:
        data = json.loads(b"".join(chunks), parse_constant=_reject_constant)
    except RecursionError:
        raise too_deep from None
    except ValueError:  # includes bad JSON and bad UTF-8
        raise _invalid("Request body must be valid JSON") from None

    if _nested_deeper_than(data, MAX_JSON_DEPTH):
        raise too_deep

    try:
        parsed = PublishEventRequest.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None

    return IncomingEvent(
        event_type=parsed.event_type,
        idempotency_key=parsed.idempotency_key,
        payload=parsed.payload,
        fingerprint=compute_fingerprint(parsed.event_type, parsed.payload),
    )


IncomingEventDep = Annotated[IncomingEvent, Depends(read_incoming_event)]