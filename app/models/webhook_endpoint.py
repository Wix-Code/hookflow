import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    url: Mapped[str] = mapped_column(sa.String(2048))
    # Encrypted, never returned by the API after creation or rotation. See app/core/crypto.py.
    encrypted_signing_secret: Mapped[str] = mapped_column(sa.String(512))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, server_default=sa.true())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )
    # "Removing" an endpoint only sets this. The row stays so that past deliveries keep pointing at it.
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class EndpointSubscription(Base):
    """One row per event type an endpoint wants. Matching is exact: "payment.successful" only."""

    __tablename__ = "endpoint_subscriptions"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(sa.String(200), primary_key=True, index=True)