import uuid

from fastapi import APIRouter, Response

from app.api.deps import DbSession, EndpointCtx, ProjectCtx, SettingsDep
from app.schemas.endpoint import (
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    EndpointWithSecret,
)
from app.schemas.response import ApiResponse, ErrorResponse
from app.services import endpoints as endpoint_service

router = APIRouter(tags=["endpoints"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}
_BAD_URL = {422: {"model": ErrorResponse, "description": "Validation failed, or the URL is not allowed"}}


@router.post(
    "/projects/{project_id}/endpoints",
    response_model=ApiResponse[EndpointWithSecret],
    status_code=201,
    responses={
        **_NOT_FOUND,
        **_BAD_URL,
        409: {"model": ErrorResponse, "description": "The project already has 25 endpoints"},
    },
)
def create_endpoint(
    project_id: uuid.UUID,
    body: EndpointCreate,
    ctx: ProjectCtx,
    db: DbSession,
    settings: SettingsDep,
    response: Response,
):
    endpoint, secret = endpoint_service.create_endpoint(
        db, ctx, name=body.name, url=body.url, event_types=body.event_types, settings=settings
    )
    response.headers["Cache-Control"] = "no-store"  # a reply with a secret in it must not be cached
    return ApiResponse(
        message="Endpoint created. Copy the signing secret now, it will not be shown again",
        data=EndpointWithSecret.from_endpoint_and_secret(
            endpoint, endpoint_service.event_types_for(db, endpoint.id), secret
        ),
    )


@router.get(
    "/projects/{project_id}/endpoints",
    response_model=ApiResponse[list[EndpointResponse]],
    responses=_NOT_FOUND,
)
def list_endpoints(project_id: uuid.UUID, ctx: ProjectCtx, db: DbSession):
    rows = endpoint_service.list_endpoints(db, ctx)
    return ApiResponse(
        message="Endpoints",
        data=[EndpointResponse.from_endpoint(endpoint, types) for endpoint, types in rows],
    )


@router.get("/endpoints/{endpoint_id}", response_model=ApiResponse[EndpointResponse], responses=_NOT_FOUND)
def get_endpoint(endpoint_id: uuid.UUID, ctx: EndpointCtx, db: DbSession):
    types = endpoint_service.event_types_for(db, ctx.endpoint.id)
    return ApiResponse(message="Endpoint", data=EndpointResponse.from_endpoint(ctx.endpoint, types))


@router.patch(
    "/endpoints/{endpoint_id}",
    response_model=ApiResponse[EndpointResponse],
    responses={**_NOT_FOUND, **_BAD_URL},
)
def update_endpoint(
    endpoint_id: uuid.UUID, body: EndpointUpdate, ctx: EndpointCtx, db: DbSession, settings: SettingsDep
):
    endpoint, types = endpoint_service.update_endpoint(db, ctx, body, settings)
    return ApiResponse(message="Endpoint updated", data=EndpointResponse.from_endpoint(endpoint, types))


@router.delete("/endpoints/{endpoint_id}", response_model=ApiResponse[None], responses=_NOT_FOUND)
def remove_endpoint(endpoint_id: uuid.UUID, ctx: EndpointCtx, db: DbSession):
    endpoint_service.remove_endpoint(db, ctx)
    return ApiResponse(message="Endpoint removed. Its delivery history is kept")


@router.post(
    "/endpoints/{endpoint_id}/rotate-secret",
    response_model=ApiResponse[EndpointWithSecret],
    responses=_NOT_FOUND,
)
def rotate_secret(
    endpoint_id: uuid.UUID, ctx: EndpointCtx, db: DbSession, settings: SettingsDep, response: Response
):
    endpoint, types, secret = endpoint_service.rotate_secret(db, ctx, settings)
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(
        message="Secret rotated. The old secret no longer works. Copy the new one now, it will not be shown again",
        data=EndpointWithSecret.from_endpoint_and_secret(endpoint, types, secret),
    )