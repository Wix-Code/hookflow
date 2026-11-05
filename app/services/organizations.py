import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.models import Organization, OrganizationMember, User
from app.models.enums import Role
from app.services.tenancy import OrgContext


def create_organization(db: Session, user: User, name: str, slug: str) -> Organization:
    organization = Organization(name=name, slug=slug, owner_id=user.id)
    try:
        db.add(organization)
        db.flush()  # sends the INSERT now, so a duplicate slug fails here
    except IntegrityError:
        db.rollback()
        raise Conflict("organization_slug_taken", "This organization slug is already taken") from None

    # Same transaction: the organization and its first owner are saved together or not at all.
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=Role.OWNER.value))
    db.commit()
    return organization


def list_organizations(db: Session, user_id: uuid.UUID) -> list[tuple[Organization, str]]:
    rows = db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at, Organization.id)
    ).all()
    return [(organization, role) for organization, role in rows]


def update_organization(db: Session, ctx: OrgContext, changes: dict) -> Organization:
    if "name" in changes:
        ctx.organization.name = changes["name"]
    db.commit()
    return ctx.organization


def list_members(db: Session, ctx: OrgContext) -> list[tuple[OrganizationMember, User]]:
    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == ctx.organization.id)
        .order_by(OrganizationMember.created_at, User.email)
    ).all()
    return [(member, user) for member, user in rows]


def invite_member(db: Session, ctx: OrgContext, email: str, role: Role) -> tuple[OrganizationMember, User]:
    # MVP: "invite" means adding someone who already has an account.
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        raise NotFound("user_not_found", "No registered user with this email")

    if db.get(OrganizationMember, (ctx.organization.id, user.id)) is not None:
        raise Conflict("already_member", "This user is already a member")

    member = OrganizationMember(organization_id=ctx.organization.id, user_id=user.id, role=role.value)
    db.add(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("already_member", "This user is already a member") from None
    return member, user


def remove_member(db: Session, ctx: OrgContext, user_id: uuid.UUID) -> None:
    # Lock the organization row first. Without this, two owners removing each other at the
    # same moment could both pass the "is there another owner?" check and leave zero owners.
    db.scalar(select(Organization.id).where(Organization.id == ctx.organization.id).with_for_update())

    target = db.get(OrganizationMember, (ctx.organization.id, user_id))
    if target is None:
        raise NotFound("member_not_found", "Member not found")

    if target.role == Role.OWNER:
        owner_count = db.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == ctx.organization.id,
                OrganizationMember.role == Role.OWNER.value,
            )
        )
        if owner_count <= 1:
            raise Conflict("last_owner", "The last owner cannot be removed")

    db.delete(target)
    db.commit()