import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.errors import AppError, Conflict
from app.models import Event, Project
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


def _replay(existing: Event, incoming: IncomingEvent) -> tuple[Event, bool]:
    if existing.fingerprint == incoming.fingerprint:
        return existing, True  # the same request again: hand back the original event
    raise Conflict(
        "idempotency_key_conflict", "This idempotency key was already used with a different request body"
    )


def publish_event(db: Session, project: Project, incoming: IncomingEvent) -> tuple[Event, bool]:
    """Returns (event, duplicate). duplicate is True when an earlier identical request is being repeated."""
    project_id = project.id  # read now: a rollback below would expire the object

    if project.status == ProjectStatus.ARCHIVED:
        raise Conflict("project_archived", "This project is archived and no longer accepts events")

    if incoming.idempotency_key is not None:
        existing = _find_by_key(db, project_id, incoming.idempotency_key)
        if existing is not None:
            return _replay(existing, incoming)

    event = Event(
        project_id=project_id,
        event_type=incoming.event_type,
        payload=incoming.payload,
        idempotency_key=incoming.idempotency_key,
        fingerprint=incoming.fingerprint,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests arrived at once and the other one won. The database's unique index
        # decided, so look the winner up and treat this request as the repeat it is.
        db.rollback()
        if incoming.idempotency_key is None:
            raise
        existing = _find_by_key(db, project_id, incoming.idempotency_key)
        if existing is None:
            raise
        return _replay(existing, incoming)
    except DataError:
        # For example text that PostgreSQL cannot store inside JSON (a NUL character).
        db.rollback()
        raise AppError(422, "invalid_payload", "The payload contains characters that cannot be stored") from None
    return event, False


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