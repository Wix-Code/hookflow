import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import AwareDatetime

from app.api.deps import ApiKeyCtx, DbSession, EventCtx, PageParams, ProjectCtx
from app.api.event_body import IncomingEventDep
from app.schemas.event import EventAccepted, EventDetail, EventSummary, PublishEventRequest
from app.schemas.response import ApiResponse, ErrorResponse, Page
from app.services import events as event_service

router = APIRouter(tags=["events"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}

# The body is read by hand (see api/event_body.py), so tell Swagger what it looks like.
_PUBLISH_BODY_DOCS = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": PublishEventRequest.model_json_schema()}},
    }
}


@router.post(
    "/projects/{project_id}/events",
    response_model=ApiResponse[EventAccepted],
    status_code=202,
    openapi_extra=_PUBLISH_BODY_DOCS,
    responses={
        200: {"model": ApiResponse[EventAccepted], "description": "Repeat of an event already accepted"},
        401: {"model": ErrorResponse, "description": "Missing, invalid, revoked or expired API key"},
        403: {"model": ErrorResponse, "description": "API key belongs to another project"},
        409: {"model": ErrorResponse, "description": "Archived project, or idempotency key reused with a different body"},
        413: {"model": ErrorResponse, "description": "Body larger than 256 KB"},
    },
)
def publish_event(
    project_id: uuid.UUID,
    key_ctx: ApiKeyCtx,  # listed first: the key is checked before we read the body
    incoming: IncomingEventDep,
    db: DbSession,
    response: Response,
):
    event, duplicate = event_service.publish_event(db, key_ctx.project, incoming)
    if duplicate:
        response.status_code = 200
    return ApiResponse(
        message="Event already accepted" if duplicate else "Event accepted",
        data=EventAccepted(
            id=event.id,
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            duplicate=duplicate,
            created_at=event.created_at,
        ),
    )


@router.get(
    "/projects/{project_id}/events",
    response_model=ApiResponse[Page[EventSummary]],
    responses=_NOT_FOUND,
)
def list_events(
    project_id: uuid.UUID,
    ctx: ProjectCtx,
    page: PageParams,
    db: DbSession,
    event_type: Annotated[str | None, Query(max_length=200, description="Exact event type")] = None,
    created_from: Annotated[AwareDatetime | None, Query(description="Created at or after (needs a timezone)")] = None,
    created_to: Annotated[AwareDatetime | None, Query(description="Created before (needs a timezone)")] = None,
):
    events, total = event_service.list_events(
        db,
        ctx,
        event_type=event_type,
        created_from=created_from,
        created_to=created_to,
        limit=page.limit,
        offset=page.offset,
    )
    return ApiResponse(
        message="Events",
        data=Page(
            items=[EventSummary.model_validate(event) for event in events],
            total=total,
            limit=page.limit,
            offset=page.offset,
        ),
    )


@router.get("/events/{event_id}", response_model=ApiResponse[EventDetail], responses=_NOT_FOUND)
def get_event(event_id: uuid.UUID, ctx: EventCtx):
    return ApiResponse(message="Event", data=EventDetail.model_validate(ctx.event))