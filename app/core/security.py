import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

_hasher = PasswordHasher()

# A real hash that nobody's password matches. We check against it when the email is
# unknown, so "no such user" takes about as long as "wrong password".
_DUMMY_HASH = _hasher.hash("hookflow-timing-equaliser")


class TokenError(Exception):
    """Raised when an access token cannot be trusted. Carries a code and a message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, settings: Settings) -> str:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": "access",
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "sid", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("token_expired", "Access token has expired") from None
    except jwt.PyJWTError:
        raise TokenError("invalid_token", "Access token is invalid") from None

    if payload.get("typ") != "access":
        raise TokenError("invalid_token", "Access token is invalid")

    try:
        return AccessClaims(user_id=uuid.UUID(payload["sub"]), session_id=uuid.UUID(payload["sid"]))
    except (ValueError, TypeError):
        raise TokenError("invalid_token", "Access token is invalid") from None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()