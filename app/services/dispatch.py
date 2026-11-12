"""The delivery state machine: find what is due, lease it, send it, record the result.

    pending ──► processing ──► succeeded
                    │
                    ├──► retry_scheduled ──► processing ... (up to 5 attempts in total)
                    └──► failed

Rules that make this safe when several workers run at once or a worker dies half way:
  * claiming is a compare-and-swap UPDATE, so exactly one worker wins a delivery
  * the winner gets a lease (a token and an expiry). Only the holder of the current token can record the result,
    so a slow worker that lost its lease cannot overwrite what the new holder did
  * a lease that expires is treated as a lost attempt (recorded as such) and the delivery is picked up again
  * "succeeded" is never claimed again, so a successful delivery is never sent twice by us
  * no database connection is held open while we wait for the network
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import decrypt_secret
from app.core.sender import Outcome, SendResult, send_webhook
from app.core.signing import sign_payload
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import Delivery, DeliveryAttempt, Event, OutboxMessage, WebhookEndpoint
from app.models.enums import DeliveryStatus, OutboxStatus

logger = logging.getLogger("hookflow.worker")

MAX_ATTEMPTS = 5
# Wait after attempt 1, 2, 3, 4 fails: 1 minute, 5 minutes, 15 minutes, 1 hour. A fifth failure is final.
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600)

_WAITING = (DeliveryStatus.PENDING.value, DeliveryStatus.RETRY_SCHEDULED.value)


@dataclass(frozen=True)
class Claim:
    delivery_id: uuid.UUID
    lease_token: uuid.UUID
    attempt_number: int  # the attempt we are about to make


def _is_due(now: datetime):
    waiting = and_(
        Delivery.status.in_(_WAITING),
        or_(Delivery.next_retry_at.is_(None), Delivery.next_retry_at <= now),
    )
    abandoned = and_(Delivery.status == DeliveryStatus.PROCESSING.value, Delivery.lease_expires_at < now)
    return or_(waiting, abandoned)


def _close_outbox_note(db: Session, delivery_id: uuid.UUID, now: datetime) -> None:
    """Without a message broker, "picked up by a worker" is what publishing the outbox note means."""
    db.execute(
        update(OutboxMessage)
        .where(OutboxMessage.delivery_id == delivery_id, OutboxMessage.status == OutboxStatus.PENDING.value)
        .values(status=OutboxStatus.PUBLISHED.value, published_at=now)
    )


def claim_due_deliveries(
    db: Session, *, limit: int, lease_seconds: int, now: datetime | None = None
) -> list[Claim]:
    now = now or utcnow()
    expires = now + timedelta(seconds=lease_seconds)

    # Only deliveries of endpoints that are switched on and not removed. SKIP LOCKED lets several workers
    # run this at the same moment without waiting for each other: each one simply skips rows another holds.
    candidates = db.execute(
        select(Delivery.id, Delivery.status, Delivery.attempt_count)
        .join(WebhookEndpoint, WebhookEndpoint.id == Delivery.endpoint_id)
        .where(_is_due(now), WebhookEndpoint.is_active.is_(True), WebhookEndpoint.deleted_at.is_(None))
        .order_by(func.coalesce(Delivery.next_retry_at, Delivery.created_at), Delivery.id)
        .limit(limit)
        .with_for_update(skip_locked=True, of=Delivery)
    ).all()

    claims: list[Claim] = []
    for delivery_id, seen_status, attempts_so_far in candidates:
        token = uuid.uuid4()
        if seen_status == DeliveryStatus.PROCESSING.value:
            # A worker took this and never reported back. Count its try as lost and move on.
            won = db.execute(
                update(Delivery)
                .where(Delivery.id == delivery_id, _is_due(now))
                .values(
                    attempt_count=Delivery.attempt_count + 1,
                    lease_token=token,
                    lease_expires_at=expires,
                    updated_at=now,
                )
            )
            if won.rowcount != 1:
                continue
            attempts_so_far += 1
            db.add(
                DeliveryAttempt(
                    delivery_id=delivery_id,
                    attempt_number=attempts_so_far,
                    response_status=None,
                    duration_ms=None,
                    error="lease_expired",
                    attempted_at=now,
                )
            )
            if attempts_so_far >= MAX_ATTEMPTS:
                db.execute(
                    update(Delivery)
                    .where(Delivery.id == delivery_id)
                    .values(
                        status=DeliveryStatus.FAILED.value,
                        next_retry_at=None,
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                continue
        else:
            won = db.execute(
                update(Delivery)
                .where(Delivery.id == delivery_id, _is_due(now))
                .values(
                    status=DeliveryStatus.PROCESSING.value,
                    lease_token=token,
                    lease_expires_at=expires,
                    updated_at=now,
                )
            )
            if won.rowcount != 1:
                continue  # another worker got there first
            if attempts_so_far == 0:
                _close_outbox_note(db, delivery_id, now)
        claims.append(Claim(delivery_id=delivery_id, lease_token=token, attempt_number=attempts_so_far + 1))
    db.commit()
    return claims


def cancel_deliveries_of_removed_endpoints(db: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """A removed endpoint can never be sent to, so its waiting deliveries end as failed (and say why)."""
    now = now or utcnow()
    rows = db.execute(
        select(Delivery.id, Delivery.attempt_count)
        .join(WebhookEndpoint, WebhookEndpoint.id == Delivery.endpoint_id)
        .where(WebhookEndpoint.deleted_at.is_not(None), Delivery.status.in_(_WAITING))
        .limit(limit)
        .with_for_update(skip_locked=True, of=Delivery)
    ).all()
    cancelled = 0
    for delivery_id, attempts_so_far in rows:
        won = db.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id, Delivery.status.in_(_WAITING))
            .values(
                status=DeliveryStatus.FAILED.value,
                attempt_count=attempts_so_far + 1,
                next_retry_at=None,
                updated_at=now,
            )
        )
        if won.rowcount != 1:
            continue
        db.add(
            DeliveryAttempt(
                delivery_id=delivery_id,
                attempt_number=attempts_so_far + 1,
                response_status=None,
                duration_ms=0,
                error="endpoint_removed",
                attempted_at=now,
            )
        )
        _close_outbox_note(db, delivery_id, now)
        cancelled += 1
    db.commit()
    return cancelled


def release_claim(db: Session, claim: Claim, now: datetime | None = None) -> None:
    """Give a delivery back untouched (for example the endpoint was switched off after we claimed it)."""
    db.execute(
        update(Delivery)
        .where(
            Delivery.id == claim.delivery_id,
            Delivery.lease_token == claim.lease_token,
            Delivery.status == DeliveryStatus.PROCESSING.value,
        )
        .values(
            status=DeliveryStatus.PENDING.value if claim.attempt_number == 1 else DeliveryStatus.RETRY_SCHEDULED.value,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now or utcnow(),
        )
    )
    db.commit()


def finish_attempt(
    db: Session,
    claim: Claim,
    result: SendResult,
    attempted_at: datetime,
    now: datetime | None = None,
) -> str | None:
    """Record the outcome. Returns the delivery's new status, or None if our lease was lost (nothing is written)."""
    now = now or utcnow()
    next_retry_at = None
    delivered_at = None
    if result.outcome == Outcome.SUCCESS:
        new_status = DeliveryStatus.SUCCEEDED.value
        delivered_at = now
    elif result.outcome == Outcome.PERMANENT or claim.attempt_number >= MAX_ATTEMPTS:
        new_status = DeliveryStatus.FAILED.value
    else:
        new_status = DeliveryStatus.RETRY_SCHEDULED.value
        next_retry_at = now + timedelta(seconds=RETRY_DELAYS_SECONDS[claim.attempt_number - 1])

    changed = db.execute(
        update(Delivery)
        .where(
            Delivery.id == claim.delivery_id,
            Delivery.lease_token == claim.lease_token,
            Delivery.status == DeliveryStatus.PROCESSING.value,
        )
        .values(
            status=new_status,
            attempt_count=claim.attempt_number,
            next_retry_at=next_retry_at,
            delivered_at=delivered_at,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    if changed.rowcount != 1:
        db.rollback()
        return None
    db.add(
        DeliveryAttempt(
            delivery_id=claim.delivery_id,
            attempt_number=claim.attempt_number,
            response_status=result.status_code,
            duration_ms=result.duration_ms,
            error=result.error,
            attempted_at=attempted_at,
        )
    )
    db.commit()
    return new_status


def build_body(event_id: uuid.UUID, event_type: str, created_at: datetime, payload: dict) -> bytes:
    envelope = {
        "id": str(event_id),
        "type": event_type,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "data": payload,
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")  # plain ASCII bytes


def process_claim(
    claim: Claim,
    settings: Settings,
    *,
    send: Callable[..., SendResult] = send_webhook,
    now: datetime | None = None,
) -> str | None:
    # 1. Read everything we need, then let go of the database connection before touching the network.
    with SessionLocal() as db:
        delivery = db.execute(
            select(Delivery.event_id, Delivery.endpoint_id).where(Delivery.id == claim.delivery_id)
        ).one()
        endpoint = db.execute(
            select(
                WebhookEndpoint.url,
                WebhookEndpoint.encrypted_signing_secret,
                WebhookEndpoint.is_active,
                WebhookEndpoint.deleted_at,
            ).where(WebhookEndpoint.id == delivery.endpoint_id)
        ).one()
        event = db.execute(
            select(Event.id, Event.event_type, Event.payload, Event.created_at).where(Event.id == delivery.event_id)
        ).one()

    attempted_at = now or utcnow()
    if endpoint.deleted_at is not None:
        result = SendResult(Outcome.PERMANENT, None, "endpoint_removed", 0)
    elif not endpoint.is_active:
        with SessionLocal() as db:
            release_claim(db, claim, now)
        return None
    else:
        try:
            secret = decrypt_secret(endpoint.encrypted_signing_secret, settings)
        except InvalidToken:
            # ENCRYPTION_KEY changed since the secret was saved. The owner must rotate the secret.
            result = SendResult(Outcome.PERMANENT, None, "secret_unreadable", 0)
        else:
            body = build_body(event.id, event.event_type, event.created_at, event.payload)
            timestamp = int(time.time())  # fresh on every attempt, so a late retry is not rejected as old
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "HookFlow/1.0",
                "X-HookFlow-Event-ID": str(event.id),
                "X-HookFlow-Delivery-ID": str(claim.delivery_id),
                "X-HookFlow-Timestamp": str(timestamp),
                "X-HookFlow-Signature": sign_payload(secret, timestamp, body),
            }
            try:
                result = send(endpoint.url, body, headers, settings)
            except Exception as exc:  # a bug must not kill the worker or lose the attempt
                logger.error("delivery %s: unexpected %s while sending", claim.delivery_id, type(exc).__name__)
                result = SendResult(Outcome.RETRY, None, "internal_error", 0)

    # 2. Record the result.
    with SessionLocal() as db:
        new_status = finish_attempt(db, claim, result, attempted_at, now)
    if new_status is None:
        logger.warning("delivery %s: lease was lost, result discarded", claim.delivery_id)
    else:
        logger.info(
            "delivery %s attempt %s: %s (http=%s, %s ms, error=%s)",
            claim.delivery_id,
            claim.attempt_number,
            new_status,
            result.status_code,
            result.duration_ms,
            result.error,
        )
    return new_status


def run_once(
    settings: Settings,
    *,
    limit: int,
    executor: Executor | None = None,
    send: Callable[..., SendResult] = send_webhook,
    now: datetime | None = None,
) -> int:
    """One pass: tidy up, claim what is due, send it (in parallel if an executor is given). Returns how many."""
    with SessionLocal() as db:
        cancel_deliveries_of_removed_endpoints(db, now=now)
        claims = claim_due_deliveries(db, limit=limit, lease_seconds=settings.delivery_lease_seconds, now=now)
    if executor is None:
        for claim in claims:
            process_claim(claim, settings, send=send, now=now)
    else:
        list(executor.map(lambda c: process_claim(c, settings, send=send, now=now), claims))
    return len(claims)