import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import WebhookEndpoint
from app.schemas.common import Name
from app.schemas.event import EventType

MAX_EVENT_TYPES_PER_ENDPOINT = 50

# The URL text is checked for safety in the service (it needs a setting). Here we only bound the size.
WebhookUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]


def _unique_in_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))  # "a, b, a" becomes "a, b"


EventTypeList = Annotated[
    list[EventType],
    Field(min_length=1, max_length=MAX_EVENT_TYPES_PER_ENDPOINT),
    AfterValidator(_unique_in_order),
]


class EndpointCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Billing service",
                    "url": "https://hooks.example.com/hookflow",
                    "event_types": ["payment.successful", "payment.failed"],
                }
            ]
        },
    )

    name: Name
    url: WebhookUrl
    event_types: EventTypeList


class EndpointUpdate(BaseModel):
    """Send only the fields you want to change."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    url: WebhookUrl | None = None
    event_types: EventTypeList | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one_real_change(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        # "url": null is not a way to clear the url.
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Fields that are sent must not be null")
        return self


class EndpointResponse(BaseModel):
    """Never contains the signing secret. Only creation and rotation reveal it."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    url: str
    event_types: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_endpoint(cls, endpoint: WebhookEndpoint, event_types: list[str]) -> "EndpointResponse":
        return cls(
            id=endpoint.id,
            project_id=endpoint.project_id,
            name=endpoint.name,
            url=endpoint.url,
            event_types=sorted(event_types),
            is_active=endpoint.is_active,
            created_at=endpoint.created_at,
            updated_at=endpoint.updated_at,
        )


class EndpointWithSecret(EndpointResponse):
    """The reply to create and rotate. The only place the secret ever appears, and only once."""

    signing_secret: str

    @classmethod
    def from_endpoint_and_secret(
        cls, endpoint: WebhookEndpoint, event_types: list[str], secret: str
    ) -> "EndpointWithSecret":
        return cls(**EndpointResponse.from_endpoint(endpoint, event_types).model_dump(), signing_secret=secret)