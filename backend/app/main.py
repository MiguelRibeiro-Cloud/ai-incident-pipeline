from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.config import settings

app = FastAPI(title="AI Incident Processing Pipeline", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
