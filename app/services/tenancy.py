"""The one place that decides "may this user touch this organization, project, event, endpoint or delivery?".

Every route that takes an organization, project or event id goes through these functions,
so tenant isolation cannot be forgotten on an individual endpoint.

Rule: if you are not a member, the resource looks like it does not exist (404).
If you are a member but your role is too low, you get 403.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.models import Delivery, Event, Organization, OrganizationMember, Project, WebhookEndpoint
from app.models.enums import Role


@dataclass(frozen=True)
class OrgContext:
    organization: Organization
    membership: OrganizationMember


@dataclass(frozen=True)
class ProjectContext:
    project: Project
    membership: OrganizationMember


@dataclass(frozen=True)
class EventContext:
    event: Event
    project: Project
    membership: OrganizationMember


@dataclass(frozen=True)
class EndpointContext:
    endpoint: WebhookEndpoint
    project: Project
    membership: OrganizationMember


@dataclass(frozen=True)
class DeliveryContext:
    delivery: Delivery
    event_type: str
    endpoint: WebhookEndpoint
    project: Project
    membership: OrganizationMember


def get_org_context(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgContext:
    row = db.execute(
        select(Organization, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(Organization.id == org_id, OrganizationMember.user_id == user_id)
    ).first()
    if row is None:
        # Same reply whether the id does not exist or belongs to someone else.
        raise NotFound("organization_not_found", "Organization not found")
    return OrgContext(organization=row[0], membership=row[1])


def get_project_context(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectContext:
    row = db.execute(
        select(Project, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(Project.id == project_id, OrganizationMember.user_id == user_id)
    ).first()
    if row is None:
        raise NotFound("project_not_found", "Project not found")
    return ProjectContext(project=row[0], membership=row[1])


def get_event_context(db: Session, event_id: uuid.UUID, user_id: uuid.UUID) -> EventContext:
    row = db.execute(
        select(Event, Project, OrganizationMember)
        .join(Project, Project.id == Event.project_id)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(Event.id == event_id, OrganizationMember.user_id == user_id)
    ).first()
    if row is None:
        raise NotFound("event_not_found", "Event not found")
    return EventContext(event=row[0], project=row[1], membership=row[2])


def get_endpoint_context(db: Session, endpoint_id: uuid.UUID, user_id: uuid.UUID) -> EndpointContext:
    row = db.execute(
        select(WebhookEndpoint, Project, OrganizationMember)
        .join(Project, Project.id == WebhookEndpoint.project_id)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.deleted_at.is_(None),  # a removed endpoint is gone as far as management goes
            OrganizationMember.user_id == user_id,
        )
    ).first()
    if row is None:
        raise NotFound("endpoint_not_found", "Endpoint not found")
    return EndpointContext(endpoint=row[0], project=row[1], membership=row[2])


def get_delivery_context(db: Session, delivery_id: uuid.UUID, user_id: uuid.UUID) -> DeliveryContext:
    row = db.execute(
        select(Delivery, Event.event_type, WebhookEndpoint, Project, OrganizationMember)
        .join(Event, Event.id == Delivery.event_id)
        .join(WebhookEndpoint, WebhookEndpoint.id == Delivery.endpoint_id)  # removed endpoints included: history stays
        .join(Project, Project.id == WebhookEndpoint.project_id)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(Delivery.id == delivery_id, OrganizationMember.user_id == user_id)
    ).first()
    if row is None:
        raise NotFound("delivery_not_found", "Delivery not found")
    return DeliveryContext(delivery=row[0], event_type=row[1], endpoint=row[2], project=row[3], membership=row[4])


def require_owner(membership: OrganizationMember) -> None:
    if membership.role != Role.OWNER:
        raise Forbidden("insufficient_role", "Only organization owners can do this")