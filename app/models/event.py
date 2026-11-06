import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # Fast "newest events of this project" lookups.
        sa.Index("ix_events_project_id_created_at", "project_id", "created_at"),
        # A key may be reused in different projects, but only once inside one project.
        # "Partial": events without a key are not part of this index, so they never clash.
        sa.Index(
            "uq_events_project_id_idempotency_key",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("projects.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(sa.String(200))
    # JSONB on PostgreSQL (searchable, compact), plain JSON text on SQLite.
    payload: Mapped[dict] = mapped_column(sa.JSON().with_variant(postgresql.JSONB(), "postgresql"))
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(255), default=None)
    # SHA-256 of the canonical request (event_type + payload). Used to tell a retry from a different request.
    fingerprint: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())