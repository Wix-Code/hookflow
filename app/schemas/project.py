import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ProjectStatus
from app.schemas.common import Name, Slug


class ProjectCreate(BaseModel):
    name: Name
    slug: Slug
    description: str | None = Field(default=None, max_length=1000)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None