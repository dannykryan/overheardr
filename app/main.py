"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_storage


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

_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe for Docker and native runs."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Placeholder home page — URL form ships in a later milestone."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "overheardr",
            "spotify_connected": False,
        },
    )