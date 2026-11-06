import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden, NotFound
from app.core.keys import extract_prefix, generate_api_key, hash_api_key, hashes_match
from app.db.types import utcnow
from app.models import ApiKey, Project
from app.services.tenancy import ProjectContext


@dataclass(frozen=True)
class ApiKeyContext:
    api_key: ApiKey
    project: Project


def _unauthorized(code: str, message: str) -> AppError:
    return AppError(401, code, message, headers={"WWW-Authenticate": "ApiKey"})


def issue_api_key(db: Session, ctx: ProjectContext, name: str, expires_at) -> tuple[ApiKey, str]:
    project_id = ctx.project.id  # read now: a rollback below would expire the object
    for _ in range(3):
        raw_key, prefix, secret_hash = generate_api_key()
        api_key = ApiKey(
            project_id=project_id, name=name, prefix=prefix, secret_hash=secret_hash, expires_at=expires_at
        )
        db.add(api_key)
        try:
            db.commit()
            return api_key, raw_key
        except IntegrityError:
            # Two random prefixes collided (very unlikely). Roll back and draw a new key.
            db.rollback()
    raise RuntimeError("could not generate a unique API key")


def list_api_keys(db: Session, ctx: ProjectContext) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.project_id == ctx.project.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        )
    )


def revoke_api_key(db: Session, ctx: ProjectContext, key_id: uuid.UUID) -> ApiKey:
    # Filtering by project_id means a key id from another project is simply "not found".
    api_key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == ctx.project.id))
    if api_key is None:
        raise NotFound("api_key_not_found", "API key not found")
    if api_key.revoked_at is None:  # revoking twice changes nothing
        api_key.revoked_at = utcnow()
        db.commit()
    return api_key


def authenticate_api_key(db: Session, raw_key: str | None, project_id: uuid.UUID) -> ApiKeyContext:
    if not raw_key or not raw_key.strip():
        raise _unauthorized("api_key_missing", "The X-API-Key header is required")
    raw_key = raw_key.strip()

    # Find the row by the public prefix, then compare hashes in constant time.
    prefix = extract_prefix(raw_key)
    api_key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix)) if prefix else None
    if api_key is None or not hashes_match(api_key.secret_hash, hash_api_key(raw_key)):
        raise _unauthorized("invalid_api_key", "API key is invalid")

    # From here on the caller really holds this key, so it is safe to say why it fails.
    if api_key.revoked_at is not None:
        raise _unauthorized("api_key_revoked", "This API key has been revoked")
    if api_key.expires_at is not None and api_key.expires_at <= utcnow():
        raise _unauthorized("api_key_expired", "This API key has expired")
    if api_key.project_id != project_id:
        raise Forbidden("api_key_wrong_project", "This API key does not belong to this project")

    project = db.get(Project, api_key.project_id)
    return ApiKeyContext(api_key=api_key, project=project)