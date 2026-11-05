from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.auth import RegisterRequest, UserResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: DbSession):
    return auth_service.register_user(db, body.full_name, body.email, body.password)