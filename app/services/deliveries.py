import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Delivery, DeliveryAttempt, Event, WebhookEndpoint
from app.models.enums import DeliveryStatus
from app.services.tenancy import DeliveryContext, ProjectContext


def list_deliveries(
    db: Session,
    ctx: ProjectContext,
    *,
    status: DeliveryStatus | None,
    endpoint_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
    event_type: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Delivery, str, str]], int]:
    """Returns ((delivery, event_type, endpoint_name) rows, total).

    A delivery has no project column of its own. It belongs to a project through its endpoint, and an endpoint
    that was removed is still joined here, which is what keeps the history visible after removal.
    """
    conditions = [WebhookEndpoint.project_id == ctx.project.id]
    if status is not None:
        conditions.append(Delivery.status == status.value)
    if endpoint_id is not None:
        conditions.append(Delivery.endpoint_id == endpoint_id)
    if event_id is not None:
        conditions.append(Delivery.event_id == event_id)
    if event_type is not None:
        conditions.append(Event.event_type == event_type)
    if created_from is not None:
        conditions.append(Delivery.created_at >= created_from)
    if created_to is not None:
        conditions.append(Delivery.created_at < created_to)

    joined = (
        select(Delivery)
        .join(Event, Event.id == Delivery.event_id)
        .join(WebhookEndpoint, WebhookEndpoint.id == Delivery.endpoint_id)
        .where(*conditions)
    )
    total = db.scalar(select(func.count()).select_from(joined.subquery()))
    rows = db.execute(
        joined.with_only_columns(Delivery, Event.event_type, WebhookEndpoint.name)
        .order_by(Delivery.created_at.desc(), Delivery.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [(delivery, event_type_, endpoint_name) for delivery, event_type_, endpoint_name in rows], total


def list_attempts(db: Session, ctx: DeliveryContext, *, limit: int, offset: int) -> tuple[list[DeliveryAttempt], int]:
    condition = DeliveryAttempt.delivery_id == ctx.delivery.id
    total = db.scalar(select(func.count()).select_from(DeliveryAttempt).where(condition))
    attempts = db.scalars(
        select(DeliveryAttempt).where(condition).order_by(DeliveryAttempt.attempt_number).limit(limit).offset(offset)
    ).all()
    return list(attempts), total