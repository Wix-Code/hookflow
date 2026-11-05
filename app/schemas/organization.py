import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models import Organization, OrganizationMember, User
from app.models.enums import Role
from app.schemas.common import Name, Slug


class OrganizationCreate(BaseModel):
    name: Name
    slug: Slug


class OrganizationUpdate(BaseModel):
    # forbid: sending a field we do not allow changing (like slug) is an error, not silently ignored.
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    role: Role  # the role of the user making the request
    created_at: datetime

    @classmethod
    def from_row(cls, organization: Organization, role: str) -> "OrganizationResponse":
        return cls(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            owner_id=organization.owner_id,
            role=Role(role),
            created_at=organization.created_at,
        )


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: Role = Role.DEVELOPER

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: EmailStr
    role: Role
    joined_at: datetime

    @classmethod
    def from_rows(cls, member: OrganizationMember, user: User) -> "MemberResponse":
        return cls(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=Role(member.role),
            joined_at=member.created_at,
        )