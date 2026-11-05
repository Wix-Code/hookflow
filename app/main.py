from fastapi import FastAPI

app = FastAPI(title="HookFlow")


@app.get("/health")
def health():
    return {"status": "ok"}