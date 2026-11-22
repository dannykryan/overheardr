"""HTML routes (Jinja2 + HTMX)."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import spotify_auth
from app.models import JobModel, SessionLocal, TranscriptModel
from app.pipeline import run_pipeline
from app.services import get_services
from app.spotify_auth import exchange_code
from app.youtube import validate_youtube_url

templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["web"])

_RUNNING = frozenset(
    {"queued", "fetching", "transcribing", "extracting", "matching", "creating_playlist"}
)


def _default_playlist_name(job: JobModel) -> str:
    title = job.video.title if job.video and job.video.title else "Playlist"
    channel = job.video.channel if job.video else None
    if channel and len(title) < 80:
        return f"{title} – {channel}"
    return title[:100]


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    status = spotify_auth.session_status()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "overheardr",
            "spotify_connected": status["connected"],
            "spotify_display_name": status.get("display_name"),
        },
    )


@router.post("/")
def submit_url(
    url: str = Form(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> RedirectResponse:
    try:
        validate_youtube_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with SessionLocal() as session:
        job = JobModel(url=url.strip(), status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    background_tasks.add_task(run_pipeline, job_id, get_services())
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.get("/callback")
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    try:
        return_to = exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=return_to, status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> HTMLResponse:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

    status = spotify_auth.session_status()
    poll = job.status in _RUNNING
    playlist_default = _default_playlist_name(job) if job.status == "ready" else ""
    resume = request.query_params.get("resume")

    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context={
            "job_id": job_id,
            "poll": poll,
            "spotify_connected": status["connected"],
            "spotify_display_name": status.get("display_name"),
            "playlist_default": playlist_default,
            "resume": resume if status["connected"] else None,
        },
    )


@router.get("/jobs/{job_id}/fragment", response_class=HTMLResponse)
def job_fragment(request: Request, job_id: str) -> HTMLResponse:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        albums = list(job.albums)
        video = job.video
        transcript = (
            session.query(TranscriptModel).filter(TranscriptModel.job_id == job_id).first()
        )

    bag_picks = [a for a in albums if a.role == "bag_pick"]
    mentions = [a for a in albums if a.role == "mention"]
    playlist_default = _default_playlist_name(job)

    return templates.TemplateResponse(
        request=request,
        name="job_fragment.html",
        context={
            "job": job,
            "video": video,
            "transcript": transcript,
            "bag_picks": bag_picks,
            "mentions": mentions,
            "spotify_connected": spotify_auth.session_status()["connected"],
            "playlist_default": playlist_default,
            "now": datetime.now(timezone.utc),
        },
    )