from fastapi import APIRouter

from app.api.v1 import api_keys, auth, events, organizations, projects

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.router)
api_router.include_router(api_keys.router)
api_router.include_router(events.router)