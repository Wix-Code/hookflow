import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import Delivery


class DeliveryResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    endpoint_id: uuid.UUID
    endpoint_name: str
    status: str
    attempt_count: int
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_parts(cls, delivery: Delivery, event_type: str, endpoint_name: str) -> "DeliveryResponse":
        return cls(
            id=delivery.id,
            event_id=delivery.event_id,
            event_type=event_type,
            endpoint_id=delivery.endpoint_id,
            endpoint_name=endpoint_name,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            next_retry_at=delivery.next_retry_at,
            delivered_at=delivery.delivered_at,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
        )