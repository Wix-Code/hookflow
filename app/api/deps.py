import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Unauthorized
from app.db.session import get_db
from app.models import User
from app.services import api_keys as api_key_service
from app.services import auth as auth_service
from app.services import tenancy
from app.services.api_keys import ApiKeyContext
from app.services.tenancy import EventContext, OrgContext, ProjectContext

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing credential produces our own error reply, not FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


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


def get_event_context(event_id: uuid.UUID, user: CurrentUser, db: DbSession) -> EventContext:
    """Any member of the organization that owns the event's project. Everyone else gets 404."""
    return tenancy.get_event_context(db, event_id, user.id)


def get_api_key_context(
    project_id: uuid.UUID,
    api_key: Annotated[str | None, Depends(api_key_scheme)],
    db: DbSession,
) -> ApiKeyContext:
    """Machine access: a valid project API key for exactly this project. No user is involved."""
    return api_key_service.authenticate_api_key(db, api_key, project_id)


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[int, Query(ge=1, le=100, description="Items per page (default 20, max 100)")] = 20,
    offset: Annotated[int, Query(ge=0, description="Items to skip")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


OrgMemberCtx = Annotated[OrgContext, Depends(get_org_context)]
OrgOwnerCtx = Annotated[OrgContext, Depends(get_org_owner_context)]
ProjectCtx = Annotated[ProjectContext, Depends(get_project_context)]
EventCtx = Annotated[EventContext, Depends(get_event_context)]
ApiKeyCtx = Annotated[ApiKeyContext, Depends(get_api_key_context)]
PageParams = Annotated[Pagination, Depends(get_pagination)]