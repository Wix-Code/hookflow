import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models.enums import DeliveryStatus, OutboxStatus


class Delivery(Base):
    """One event going to one endpoint. Created when the event is accepted, updated by the worker later."""

    __tablename__ = "deliveries"
    __table_args__ = (
        # The hard guarantee behind "exactly one initial delivery per endpoint": even a bug cannot add a second.
        sa.UniqueConstraint("event_id", "endpoint_id", name="uq_deliveries_event_id_endpoint_id"),
        sa.Index("ix_deliveries_status_next_retry_at", "status", "next_retry_at"),
        sa.Index("ix_deliveries_endpoint_id_created_at", "endpoint_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("events.id", ondelete="CASCADE"))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(
        sa.String(20), default=DeliveryStatus.PENDING.value, server_default=DeliveryStatus.PENDING.value
    )
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # A worker "leases" a delivery while it sends it. Only the holder of the current token may record the result.
    lease_token: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )


class DeliveryAttempt(Base):
    """One try at sending a delivery. Rows are only ever added, never changed or deleted."""

    __tablename__ = "delivery_attempts"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "attempt_number", name="uq_delivery_attempts_delivery_id_attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("deliveries.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(sa.Integer)
    response_status: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    error: Mapped[str | None] = mapped_column(sa.String(100), default=None)  # a short safe code, never raw text
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OutboxMessage(Base):
    """A note saying "this delivery needs sending", saved in the SAME transaction as the event.

    Because it is saved with the event, a crash can never leave an accepted event without its note.
    A separate process reads the unpublished notes and hands them to the queue.
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (sa.Index("ix_outbox_messages_status_created_at", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("deliveries.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(20), default=OutboxStatus.PENDING.value, server_default=OutboxStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    retry_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")