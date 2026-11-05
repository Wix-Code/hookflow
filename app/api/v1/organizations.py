import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, OrgMemberCtx, OrgOwnerCtx
from app.models.enums import Role
from app.schemas.organization import (
    InviteMemberRequest,
    MemberResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.schemas.response import ApiResponse, ErrorResponse
from app.services import organizations as org_service

router = APIRouter(prefix="/organizations", tags=["organizations"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}
_OWNER_ONLY = {
    **_NOT_FOUND,
    403: {"model": ErrorResponse, "description": "Owners only"},
}


@router.post(
    "",
    response_model=ApiResponse[OrganizationResponse],
    status_code=201,
    responses={409: {"model": ErrorResponse, "description": "Slug already taken"}},
)
def create_organization(body: OrganizationCreate, user: CurrentUser, db: DbSession):
    organization = org_service.create_organization(db, user, body.name, body.slug)
    return ApiResponse(
        message="Organization created",
        data=OrganizationResponse.from_row(organization, Role.OWNER.value),
    )


@router.get("", response_model=ApiResponse[list[OrganizationResponse]])
def list_organizations(user: CurrentUser, db: DbSession):
    rows = org_service.list_organizations(db, user.id)
    return ApiResponse(
        message="Organizations",
        data=[OrganizationResponse.from_row(organization, role) for organization, role in rows],
    )


@router.get("/{org_id}", response_model=ApiResponse[OrganizationResponse], responses=_NOT_FOUND)
def get_organization(org_id: uuid.UUID, ctx: OrgMemberCtx):
    return ApiResponse(
        message="Organization",
        data=OrganizationResponse.from_row(ctx.organization, ctx.membership.role),
    )


@router.patch("/{org_id}", response_model=ApiResponse[OrganizationResponse], responses=_OWNER_ONLY)
def update_organization(org_id: uuid.UUID, body: OrganizationUpdate, ctx: OrgOwnerCtx, db: DbSession):
    organization = org_service.update_organization(db, ctx, body.model_dump(exclude_unset=True))
    return ApiResponse(
        message="Organization updated",
        data=OrganizationResponse.from_row(organization, ctx.membership.role),
    )


@router.get("/{org_id}/members", response_model=ApiResponse[list[MemberResponse]], responses=_NOT_FOUND)
def list_members(org_id: uuid.UUID, ctx: OrgMemberCtx, db: DbSession):
    rows = org_service.list_members(db, ctx)
    return ApiResponse(
        message="Members",
        data=[MemberResponse.from_rows(member, user) for member, user in rows],
    )


@router.post(
    "/{org_id}/members",
    response_model=ApiResponse[MemberResponse],
    status_code=201,
    responses={
        **_OWNER_ONLY,
        409: {"model": ErrorResponse, "description": "Already a member"},
    },
)
def invite_member(org_id: uuid.UUID, body: InviteMemberRequest, ctx: OrgOwnerCtx, db: DbSession):
    member, user = org_service.invite_member(db, ctx, body.email, body.role)
    return ApiResponse(message="Member added", data=MemberResponse.from_rows(member, user))


@router.delete(
    "/{org_id}/members/{user_id}",
    response_model=ApiResponse[None],
    responses={
        **_OWNER_ONLY,
        409: {"model": ErrorResponse, "description": "The last owner cannot be removed"},
    },
)
def remove_member(org_id: uuid.UUID, user_id: uuid.UUID, ctx: OrgOwnerCtx, db: DbSession):
    org_service.remove_member(db, ctx, user_id)
    return ApiResponse(message="Member removed")