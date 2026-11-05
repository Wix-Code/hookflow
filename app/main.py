from fastapi import FastAPI

from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title="HookFlow")


@app.get("/health")
def health():
    return {"status": "ok"}