import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

# Letters, digits and . _ : - (for example "payment.successful"). Matching is exact and case sensitive.
EventType = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
IdempotencyKey = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class PublishEventRequest(BaseModel):
    # forbid: a typo such as "idempotency-key" is an error, not a silently ignored (and therefore unsafe) field.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "event_type": "payment.successful",
                    "idempotency_key": "pay_847_success",
                    "payload": {"payment_id": "pay_847", "amount": 15000, "currency": "NGN"},
                }
            ]
        },
    )

    event_type: EventType
    idempotency_key: IdempotencyKey | None = None
    payload: dict[str, Any]


class EventAccepted(BaseModel):
    id: uuid.UUID
    event_type: str
    status: Literal["accepted"] = "accepted"
    idempotency_key: str | None
    duplicate: bool  # true when this was a repeat of an event we already accepted
    created_at: datetime


class EventSummary(BaseModel):
    """Used in lists. The payload is left out because it can be large."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    idempotency_key: str | None
    created_at: datetime


class EventDetail(EventSummary):
    project_id: uuid.UUID
    payload: dict[str, Any]