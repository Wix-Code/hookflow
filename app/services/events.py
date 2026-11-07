import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.errors import AppError, Conflict
from app.models import Delivery, EndpointSubscription, Event, OutboxMessage, Project, WebhookEndpoint
from app.models.enums import ProjectStatus
from app.services.tenancy import ProjectContext

MAX_EVENT_BODY_BYTES = 256 * 1024  # PRD: payloads up to 256 KB


@dataclass(frozen=True)
class IncomingEvent:
    event_type: str
    idempotency_key: str | None
    payload: dict
    fingerprint: str


def compute_fingerprint(event_type: str, payload: dict) -> str:
    """A stable hash of the request. Key order and spacing do not change it, content does."""
    canonical = json.dumps(
        {"event_type": event_type, "payload": payload}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_by_key(db: Session, project_id, idempotency_key: str) -> Event | None:
    return db.scalar(
        select(Event).where(Event.project_id == project_id, Event.idempotency_key == idempotency_key)
    )


def _replay(existing: Event, incoming: IncomingEvent) -> Event:
    if existing.fingerprint == incoming.fingerprint:
        return existing  # the same request again: hand back the original event
    raise Conflict(
        "idempotency_key_conflict", "This idempotency key was already used with a different request body"
    )


def _count_deliveries(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Delivery).where(Delivery.event_id == event_id))


def _replayed(db: Session, existing: Event, incoming: IncomingEvent) -> tuple[Event, bool, int]:
    event = _replay(existing, incoming)
    return event, True, _count_deliveries(db, event.id)


def _route_event(db: Session, project_id: uuid.UUID, event: Event) -> int:
    """Create one delivery (plus its outbox note) for every active endpoint subscribed to the event's type.

    Nothing is committed here. The caller commits the event, the deliveries and the outbox notes together,
    so either all of them exist or none do.
    """
    # Step 1: lock the project's active endpoints with a SHARED lock. Shared locks do not block each other,
    # so many events can be routed at once. They do block an endpoint being edited at that same moment
    # (editing takes the exclusive lock, see services/endpoints.py). The effect is a clean cut-off: once a
    # "deactivate" request has returned, no event can create a delivery for that endpoint any more.
    active_ids = list(
        db.scalars(
            select(WebhookEndpoint.id)
            .where(
                WebhookEndpoint.project_id == project_id,
                WebhookEndpoint.is_active.is_(True),
                WebhookEndpoint.deleted_at.is_(None),
            )
            .with_for_update(read=True)
        )
    )
    if not active_ids:
        return 0

    # Step 2: which of them want this exact event type? This is a separate query on purpose, so it sees any
    # subscription change that was committed while step 1 was waiting for a lock.
    wanted_by = sorted(
        db.scalars(
            select(EndpointSubscription.endpoint_id).where(
                EndpointSubscription.endpoint_id.in_(active_ids),
                EndpointSubscription.event_type == event.event_type,
            )
        )
    )
    if not wanted_by:
        return 0

    deliveries = [Delivery(id=uuid.uuid4(), event_id=event.id, endpoint_id=endpoint_id) for endpoint_id in wanted_by]
    db.add_all(deliveries)
    db.flush()  # deliveries must exist before the outbox notes that point at them
    db.add_all(OutboxMessage(delivery_id=delivery.id) for delivery in deliveries)
    return len(deliveries)


def publish_event(db: Session, project: Project, incoming: IncomingEvent) -> tuple[Event, bool, int]:
    """Returns (event, duplicate, deliveries).

    duplicate is True when an earlier identical request is being repeated.
    deliveries is how many endpoints the event is queued for.
    """
    project_id = project.id  # read now: a rollback below would expire the object

    if project.status == ProjectStatus.ARCHIVED:
        raise Conflict("project_archived", "This project is archived and no longer accepts events")

    if incoming.idempotency_key is not None:
        existing = _find_by_key(db, project_id, incoming.idempotency_key)
        if existing is not None:
            return _replayed(db, existing, incoming)

    event = Event(
        id=uuid.uuid4(),
        project_id=project_id,
        event_type=incoming.event_type,
        payload=incoming.payload,
        idempotency_key=incoming.idempotency_key,
        fingerprint=incoming.fingerprint,
    )
    db.add(event)
    try:
        db.flush()  # the event row must exist before deliveries can point at it
        delivery_count = _route_event(db, project_id, event)
        db.commit()  # event + deliveries + outbox notes become real together, or not at all
    except IntegrityError:
        # Two identical requests arrived at once and the other one won. The database's unique index
        # decided, so look the winner up and treat this request as the repeat it is.
        db.rollback()
        if incoming.idempotency_key is None:
            raise
        existing = _find_by_key(db, project_id, incoming.idempotency_key)
        if existing is None:
            raise
        return _replayed(db, existing, incoming)
    except DataError:
        # For example text that PostgreSQL cannot store inside JSON (a NUL character).
        db.rollback()
        raise AppError(422, "invalid_payload", "The payload contains characters that cannot be stored") from None
    return event, False, delivery_count


def list_events(
    db: Session,
    ctx: ProjectContext,
    *,
    event_type: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[Event], int]:
    conditions = [Event.project_id == ctx.project.id]
    if event_type is not None:
        conditions.append(Event.event_type == event_type)
    if created_from is not None:
        conditions.append(Event.created_at >= created_from)
    if created_to is not None:
        conditions.append(Event.created_at < created_to)

    total = db.scalar(select(func.count()).select_from(Event).where(*conditions))
    events = db.scalars(
        select(Event)
        .where(*conditions)
        .options(defer(Event.payload))  # do not load big payloads we are not going to return
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(events), total