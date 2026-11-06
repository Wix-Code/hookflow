import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, field_validator

from app.db.types import utcnow
from app.models import ApiKey
from app.schemas.common import Name


class ApiKeyCreate(BaseModel):
    name: Name
    # AwareDatetime rejects "2027-01-01T00:00:00" (no timezone). Send "2027-01-01T00:00:00Z".
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def must_be_in_the_future(cls, value):
        if value is not None and value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value


class ApiKeyResponse(BaseModel):
    """What listings show. Never contains the key itself or its hash."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    prefix: str
    status: Literal["active", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_key(cls, key: ApiKey) -> "ApiKeyResponse":
        if key.revoked_at is not None:
            status = "revoked"
        elif key.expires_at is not None and key.expires_at <= utcnow():
            status = "expired"
        else:
            status = "active"
        return cls(
            id=key.id,
            project_id=key.project_id,
            name=key.name,
            prefix=key.prefix,
            status=status,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
        )


class ApiKeyCreated(ApiKeyResponse):
    """Only the creation reply carries the raw key. It cannot be retrieved again."""

    key: str

    @classmethod
    def from_key_and_secret(cls, key: ApiKey, raw_key: str) -> "ApiKeyCreated":
        return cls(**ApiKeyResponse.from_key(key).model_dump(), key=raw_key)