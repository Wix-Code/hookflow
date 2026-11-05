from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    TokenError,
    burn_password_check,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.types import utcnow
from app.models import RefreshSession, User
from app.schemas.auth import TokenResponse


def _issue_tokens(db: Session, user: User, settings: Settings) -> TokenResponse:
    """Create a session row (holding only the hash) and return a fresh access and refresh token."""
    raw_refresh_token = generate_refresh_token()
    refresh_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh_token),
        expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(refresh_session)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, refresh_session.id, settings),
        refresh_token=raw_refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


def _find_session_by_token(db: Session, raw_token: str, lock: bool = False) -> RefreshSession | None:
    statement = select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(raw_token))
    if lock:
        # Locks the row so two refreshes of the same token at once cannot both succeed.
        statement = statement.with_for_update()
    return db.scalar(statement)


def register_user(db: Session, full_name: str, email: str, password: str) -> User:
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise Conflict("email_already_registered", "An account with this email already exists")

    user = User(full_name=full_name, email=email, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("email_already_registered", "An account with this email already exists") from None
    return user


def login(db: Session, email: str, password: str, settings: Settings) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        burn_password_check(password)
        raise Unauthorized("invalid_credentials", "Invalid email or password")
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise Unauthorized("invalid_credentials", "Invalid email or password")

    return _issue_tokens(db, user, settings)


def refresh_tokens(db: Session, raw_token: str, settings: Settings) -> TokenResponse:
    refresh_session = _find_session_by_token(db, raw_token, lock=True)

    if refresh_session is None or refresh_session.revoked_at is not None:
        raise Unauthorized("invalid_refresh_token", "Refresh token is invalid")
    if refresh_session.expires_at <= utcnow():
        raise Unauthorized("refresh_token_expired", "Refresh token has expired")

    user = db.get(User, refresh_session.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("invalid_refresh_token", "Refresh token is invalid")

    # Rotation: the token just used is cancelled, and a brand new pair is issued.
    refresh_session.revoked_at = utcnow()
    return _issue_tokens(db, user, settings)


def logout(db: Session, raw_token: str) -> None:
    refresh_session = _find_session_by_token(db, raw_token)
    if refresh_session is not None and refresh_session.revoked_at is None:
        refresh_session.revoked_at = utcnow()
        db.commit()


def get_user_from_access_token(db: Session, token: str, settings: Settings) -> User:
    try:
        claims = decode_access_token(token, settings)
    except TokenError as exc:
        raise Unauthorized(exc.code, exc.message) from None

    refresh_session = db.get(RefreshSession, claims.session_id)
    if refresh_session is None or refresh_session.user_id != claims.user_id:
        raise Unauthorized("invalid_token", "Access token is invalid")
    if refresh_session.revoked_at is not None or refresh_session.expires_at <= utcnow():
        raise Unauthorized("token_revoked", "This session has ended. Log in again")

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("invalid_token", "Access token is invalid")
    return user