import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import encrypt_secret, generate_signing_secret
from app.core.errors import AppError, Conflict, NotFound
from app.core.webhook_urls import UnsafeUrl, validate_webhook_url
from app.db.types import utcnow
from app.models import EndpointSubscription, Project, WebhookEndpoint
from app.schemas.endpoint import EndpointUpdate
from app.services.tenancy import EndpointContext, ProjectContext

MAX_ENDPOINTS_PER_PROJECT = 25


def _checked_url(raw_url: str, settings: Settings) -> str:
    try:
        return validate_webhook_url(raw_url, allow_unsafe=settings.allow_unsafe_webhook_urls)
    except UnsafeUrl as exc:
        # The message explains the rule and never repeats the URL.
        raise AppError(422, "invalid_webhook_url", str(exc)) from None


def event_types_for(db: Session, endpoint_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            select(EndpointSubscription.event_type)
            .where(EndpointSubscription.endpoint_id == endpoint_id)
            .order_by(EndpointSubscription.event_type)
        )
    )


def _lock_endpoint(db: Session, endpoint: WebhookEndpoint) -> None:
    """Take the endpoint's row lock and re-read it, so changes to one endpoint happen one at a time.

    Event publishing takes a shared lock on the same row (see services/events.py). That means an event is routed
    either entirely before this change or entirely after it, never halfway through.
    """
    db.refresh(endpoint, with_for_update=True)
    if endpoint.deleted_at is not None:  # removed by someone else while we were waiting for the lock
        raise NotFound("endpoint_not_found", "Endpoint not found")


def create_endpoint(
    db: Session, ctx: ProjectContext, *, name: str, url: str, event_types: list[str], settings: Settings
) -> tuple[WebhookEndpoint, str]:
    url = _checked_url(url, settings)
    project_id = ctx.project.id

    # Lock the project row first, so two simultaneous requests cannot both slip past the limit below.
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    current = db.scalar(
        select(func.count())
        .select_from(WebhookEndpoint)
        .where(WebhookEndpoint.project_id == project_id, WebhookEndpoint.deleted_at.is_(None))
    )
    if current >= MAX_ENDPOINTS_PER_PROJECT:
        raise Conflict(
            "endpoint_limit_reached", f"A project can have at most {MAX_ENDPOINTS_PER_PROJECT} endpoints"
        )

    secret = generate_signing_secret()
    endpoint = WebhookEndpoint(
        project_id=project_id,
        name=name,
        url=url,
        encrypted_signing_secret=encrypt_secret(secret, settings),
    )
    db.add(endpoint)
    db.flush()  # the endpoint row must exist before the subscription rows that point at it
    db.add_all(EndpointSubscription(endpoint_id=endpoint.id, event_type=t) for t in event_types)
    db.commit()
    return endpoint, secret


def list_endpoints(db: Session, ctx: ProjectContext) -> list[tuple[WebhookEndpoint, list[str]]]:
    endpoints = list(
        db.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.project_id == ctx.project.id, WebhookEndpoint.deleted_at.is_(None))
            .order_by(WebhookEndpoint.created_at.desc(), WebhookEndpoint.id)
        )
    )
    types_by_endpoint: dict[uuid.UUID, list[str]] = defaultdict(list)
    if endpoints:  # one query for all of them, not one per endpoint
        rows = db.execute(
            select(EndpointSubscription.endpoint_id, EndpointSubscription.event_type).where(
                EndpointSubscription.endpoint_id.in_([e.id for e in endpoints])
            )
        )
        for endpoint_id, event_type in rows:
            types_by_endpoint[endpoint_id].append(event_type)
    return [(endpoint, types_by_endpoint[endpoint.id]) for endpoint in endpoints]


def update_endpoint(
    db: Session, ctx: EndpointContext, changes: EndpointUpdate, settings: Settings
) -> tuple[WebhookEndpoint, list[str]]:
    endpoint = ctx.endpoint
    sent = changes.model_fields_set
    new_url = _checked_url(changes.url, settings) if "url" in sent else None  # check before taking any lock

    _lock_endpoint(db, endpoint)
    if "name" in sent:
        endpoint.name = changes.name
    if "url" in sent:
        endpoint.url = new_url
    if "is_active" in sent:
        endpoint.is_active = changes.is_active
    if "event_types" in sent:
        have = set(event_types_for(db, endpoint.id))
        want = set(changes.event_types)
        gone = have - want
        if gone:
            db.execute(
                delete(EndpointSubscription).where(
                    EndpointSubscription.endpoint_id == endpoint.id,
                    EndpointSubscription.event_type.in_(gone),
                )
            )
        db.add_all(EndpointSubscription(endpoint_id=endpoint.id, event_type=t) for t in sorted(want - have))
    endpoint.updated_at = utcnow()  # also when only the subscriptions changed
    db.commit()
    return endpoint, event_types_for(db, endpoint.id)


def remove_endpoint(db: Session, ctx: EndpointContext) -> None:
    """Soft delete: the row stays so old deliveries still point at something real."""
    endpoint = ctx.endpoint
    _lock_endpoint(db, endpoint)
    now = utcnow()
    endpoint.deleted_at = now
    endpoint.is_active = False
    endpoint.updated_at = now
    db.commit()


def rotate_secret(db: Session, ctx: EndpointContext, settings: Settings) -> tuple[WebhookEndpoint, list[str], str]:
    endpoint = ctx.endpoint
    _lock_endpoint(db, endpoint)
    secret = generate_signing_secret()
    endpoint.encrypted_signing_secret = encrypt_secret(secret, settings)
    endpoint.updated_at = utcnow()
    db.commit()
    return endpoint, event_types_for(db, endpoint.id), secret