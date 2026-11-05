from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.core.security import hash_password
from app.models import User


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