import uuid

from fastapi import APIRouter, Response

from app.api.deps import DbSession, ProjectCtx
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse
from app.schemas.response import ApiResponse, ErrorResponse
from app.services import api_keys as api_key_service

router = APIRouter(tags=["api-keys"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=ApiResponse[ApiKeyCreated],
    status_code=201,
    responses=_NOT_FOUND,
)
def create_api_key(
    project_id: uuid.UUID, body: ApiKeyCreate, ctx: ProjectCtx, db: DbSession, response: Response
):
    api_key, raw_key = api_key_service.issue_api_key(db, ctx, body.name, body.expires_at)
    response.headers["Cache-Control"] = "no-store"  # a reply with a secret in it must not be cached
    return ApiResponse(
        message="API key created. Copy it now, it will not be shown again",
        data=ApiKeyCreated.from_key_and_secret(api_key, raw_key),
    )


@router.get(
    "/projects/{project_id}/api-keys",
    response_model=ApiResponse[list[ApiKeyResponse]],
    responses=_NOT_FOUND,
)
def list_api_keys(project_id: uuid.UUID, ctx: ProjectCtx, db: DbSession):
    keys = api_key_service.list_api_keys(db, ctx)
    return ApiResponse(message="API keys", data=[ApiKeyResponse.from_key(key) for key in keys])


@router.delete(
    "/projects/{project_id}/api-keys/{key_id}",
    response_model=ApiResponse[ApiKeyResponse],
    responses=_NOT_FOUND,
)
def revoke_api_key(project_id: uuid.UUID, key_id: uuid.UUID, ctx: ProjectCtx, db: DbSession):
    api_key = api_key_service.revoke_api_key(db, ctx, key_id)
    return ApiResponse(message="API key revoked", data=ApiKeyResponse.from_key(api_key))