"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.database import init_storage
from app.web import router as web_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_storage()
    yield


app = FastAPI(
    title="overheardr",
    description="Convert YouTube videos into Spotify playlists",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(auth_router)
app.include_router(web_router)

_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe for Docker and native runs."""
    return {"status": "ok"}