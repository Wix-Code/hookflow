from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.db.types import utcnow
from app.models import Project
from app.models.enums import ProjectStatus
from app.services.tenancy import OrgContext, ProjectContext


def create_project(db: Session, ctx: OrgContext, name: str, slug: str, description: str | None) -> Project:
    project = Project(organization_id=ctx.organization.id, name=name, slug=slug, description=description)
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(
            "project_slug_taken", "This slug is already used by another project in the organization"
        ) from None
    return project


def list_projects(db: Session, ctx: OrgContext) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .where(Project.organization_id == ctx.organization.id)
            .order_by(Project.created_at, Project.id)
        )
    )


def update_project(db: Session, ctx: ProjectContext, changes: dict) -> Project:
    # `changes` holds only the fields the client actually sent, so omitted fields stay untouched.
    for field, value in changes.items():
        setattr(ctx.project, field, value)
    db.commit()
    return ctx.project


def archive_project(db: Session, ctx: ProjectContext) -> Project:
    # Safe to call twice: an already archived project is returned unchanged.
    if ctx.project.status != ProjectStatus.ARCHIVED:
        ctx.project.status = ProjectStatus.ARCHIVED.value
        ctx.project.archived_at = utcnow()
        db.commit()
    return ctx.project