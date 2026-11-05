import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Unauthorized
from app.db.session import get_db
from app.models import User
from app.services import auth as auth_service
from app.services import tenancy
from app.services.tenancy import OrgContext, ProjectContext

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing token produces our own error reply, not FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
    settings: SettingsDep,
) -> User:
    if credentials is None:
        raise Unauthorized()
    return auth_service.get_user_from_access_token(db, credentials.credentials, settings)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_org_context(org_id: uuid.UUID, user: CurrentUser, db: DbSession) -> OrgContext:
    """Any member of the organization. Non-members get 404."""
    return tenancy.get_org_context(db, org_id, user.id)


def get_org_owner_context(ctx: Annotated[OrgContext, Depends(get_org_context)]) -> OrgContext:
    """Owners only. Members with another role get 403."""
    tenancy.require_owner(ctx.membership)
    return ctx


def get_project_context(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectContext:
    """Any member of the project's organization. Everyone else gets 404."""
    return tenancy.get_project_context(db, project_id, user.id)


OrgMemberCtx = Annotated[OrgContext, Depends(get_org_context)]
OrgOwnerCtx = Annotated[OrgContext, Depends(get_org_owner_context)]
ProjectCtx = Annotated[ProjectContext, Depends(get_project_context)]