import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models.enums import ProjectStatus


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        # The same slug may exist in different organizations, but only once inside one.
        sa.UniqueConstraint("organization_id", "slug", name="uq_projects_organization_id_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    slug: Mapped[str] = mapped_column(sa.String(50))
    description: Mapped[str | None] = mapped_column(sa.String(1000), default=None)
    status: Mapped[str] = mapped_column(
        sa.String(20), default=ProjectStatus.ACTIVE.value, server_default=ProjectStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)