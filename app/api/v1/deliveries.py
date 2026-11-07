import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.deps import DbSession, DeliveryCtx, PageParams, ProjectCtx
from app.models.enums import DeliveryStatus
from app.schemas.delivery import DeliveryResponse
from app.schemas.response import ApiResponse, ErrorResponse, Page
from app.services import deliveries as delivery_service

router = APIRouter(tags=["deliveries"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}


@router.get(
    "/projects/{project_id}/deliveries",
    response_model=ApiResponse[Page[DeliveryResponse]],
    responses=_NOT_FOUND,
)
def list_deliveries(
    project_id: uuid.UUID,
    ctx: ProjectCtx,
    page: PageParams,
    db: DbSession,
    status: Annotated[DeliveryStatus | None, Query(description="Delivery status")] = None,
    endpoint_id: Annotated[uuid.UUID | None, Query(description="Only this endpoint")] = None,
    event_id: Annotated[uuid.UUID | None, Query(description="Only deliveries of this event")] = None,
    event_type: Annotated[str | None, Query(max_length=200, description="Exact event type")] = None,
    created_from: Annotated[AwareDatetime | None, Query(description="Created at or after (needs a timezone)")] = None,
    created_to: Annotated[AwareDatetime | None, Query(description="Created before (needs a timezone)")] = None,
):
    rows, total = delivery_service.list_deliveries(
        db,
        ctx,
        status=status,
        endpoint_id=endpoint_id,
        event_id=event_id,
        event_type=event_type,
        created_from=created_from,
        created_to=created_to,
        limit=page.limit,
        offset=page.offset,
    )
    return ApiResponse(
        message="Deliveries",
        data=Page(
            items=[DeliveryResponse.from_parts(d, event_type_, name) for d, event_type_, name in rows],
            total=total,
            limit=page.limit,
            offset=page.offset,
        ),
    )


@router.get("/deliveries/{delivery_id}", response_model=ApiResponse[DeliveryResponse], responses=_NOT_FOUND)
def get_delivery(delivery_id: uuid.UUID, ctx: DeliveryCtx):
    return ApiResponse(
        message="Delivery",
        data=DeliveryResponse.from_parts(ctx.delivery, ctx.event_type, ctx.endpoint.name),
    )