import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(120))
    slug: Mapped[str] = mapped_column(sa.String(50), unique=True)
    # The user who created it. Ownership itself lives in organization_members (there can be several owners).
    owner_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    # Two columns together are the primary key, so a user can only appear once per organization.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(sa.String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())