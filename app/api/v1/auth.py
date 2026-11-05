from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.response import ApiResponse, ErrorResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=201,
    responses={409: {"model": ErrorResponse, "description": "Email already registered"}},
)
def register(body: RegisterRequest, db: DbSession):
    user = auth_service.register_user(db, body.full_name, body.email, body.password)
    return ApiResponse(message="Account created", data=UserResponse.model_validate(user))


@router.post(
    "/login",
    response_model=ApiResponse[TokenResponse],
    responses={401: {"model": ErrorResponse, "description": "Invalid email or password"}},
)
def login(body: LoginRequest, db: DbSession, settings: SettingsDep):
    tokens = auth_service.login(db, body.email, body.password, settings)
    return ApiResponse(message="Login successful", data=tokens)


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenResponse],
    responses={401: {"model": ErrorResponse, "description": "Refresh token invalid, used or expired"}},
)
def refresh(body: RefreshRequest, db: DbSession, settings: SettingsDep):
    tokens = auth_service.refresh_tokens(db, body.refresh_token, settings)
    return ApiResponse(message="Token refreshed", data=tokens)


@router.post("/logout", response_model=ApiResponse[None])
def logout(body: RefreshRequest, db: DbSession):
    auth_service.logout(db, body.refresh_token)
    return ApiResponse(message="Logged out")


@router.get(
    "/me",
    response_model=ApiResponse[UserResponse],
    responses={401: {"model": ErrorResponse, "description": "Missing, invalid, expired or ended session"}},
)
def me(user: CurrentUser):
    return ApiResponse(message="Current user", data=UserResponse.model_validate(user))