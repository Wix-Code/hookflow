import uuid

from fastapi import APIRouter

from app.api.deps import DbSession, OrgMemberCtx, ProjectCtx
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.schemas.response import ApiResponse, ErrorResponse
from app.services import projects as project_service

# No prefix here: project routes live under two different paths (/organizations/... and /projects/...).
router = APIRouter(tags=["projects"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found, or you are not a member"}}


@router.post(
    "/organizations/{org_id}/projects",
    response_model=ApiResponse[ProjectResponse],
    status_code=201,
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "Slug already used in this organization"},
    },
)
def create_project(org_id: uuid.UUID, body: ProjectCreate, ctx: OrgMemberCtx, db: DbSession):
    project = project_service.create_project(db, ctx, body.name, body.slug, body.description)
    return ApiResponse(message="Project created", data=ProjectResponse.model_validate(project))


@router.get(
    "/organizations/{org_id}/projects",
    response_model=ApiResponse[list[ProjectResponse]],
    responses=_NOT_FOUND,
)
def list_projects(org_id: uuid.UUID, ctx: OrgMemberCtx, db: DbSession):
    projects = project_service.list_projects(db, ctx)
    return ApiResponse(
        message="Projects", data=[ProjectResponse.model_validate(project) for project in projects]
    )


@router.get("/projects/{project_id}", response_model=ApiResponse[ProjectResponse], responses=_NOT_FOUND)
def get_project(project_id: uuid.UUID, ctx: ProjectCtx):
    return ApiResponse(message="Project", data=ProjectResponse.model_validate(ctx.project))


@router.patch("/projects/{project_id}", response_model=ApiResponse[ProjectResponse], responses=_NOT_FOUND)
def update_project(project_id: uuid.UUID, body: ProjectUpdate, ctx: ProjectCtx, db: DbSession):
    project = project_service.update_project(db, ctx, body.model_dump(exclude_unset=True))
    return ApiResponse(message="Project updated", data=ProjectResponse.model_validate(project))


@router.post(
    "/projects/{project_id}/archive", response_model=ApiResponse[ProjectResponse], responses=_NOT_FOUND
)
def archive_project(project_id: uuid.UUID, ctx: ProjectCtx, db: DbSession):
    project = project_service.archive_project(db, ctx)
    return ApiResponse(message="Project archived", data=ProjectResponse.model_validate(project))