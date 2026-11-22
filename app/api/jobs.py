"""JSON API routes for jobs."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.models import AlbumRowModel, JobModel, SessionLocal, TranscriptModel, VideoModel
from app.pipeline import run_pipeline
from app.schemas import (
    AlbumRowOut,
    CreateJobRequest,
    CreateJobResponse,
    JobDetailOut,
    JobStatus,
    PatchAlbumRequest,
    TranscriptOut,
    VideoOut,
)
from app.services import get_services
from app.youtube import validate_youtube_url

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=CreateJobResponse, status_code=201)
def create_job(body: CreateJobRequest, background_tasks: BackgroundTasks) -> CreateJobResponse:
    try:
        validate_youtube_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with SessionLocal() as session:
        job = JobModel(url=body.url.strip(), status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id
        status: JobStatus = job.status  # type: ignore[assignment]

    background_tasks.add_task(run_pipeline, job_id, get_services())
    return CreateJobResponse(id=job_id, status=status)


def _album_out(row: AlbumRowModel) -> AlbumRowOut:
    return AlbumRowOut(
        id=row.id,
        artist=row.artist,
        album=row.album,
        year=row.year,
        alternate_titles=row.alternate_titles,
        role=row.role,
        sources=row.sources,
        confidence=row.confidence,
        evidence=row.evidence,
        speaker=row.speaker,
        selected=row.selected,
        on_spotify=row.on_spotify,
        spotify_album_id=row.spotify_album_id,
        spotify_url=row.spotify_url,
        spotify_album_name=row.spotify_album_name,
        spotify_artist_name=row.spotify_artist_name,
        match_score=row.match_score,
        cover_url=row.cover_url,
        musicbrainz_release_group_id=row.musicbrainz_release_group_id,
        unavailable_reason=row.unavailable_reason,
    )


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str) -> JobDetailOut:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        video_out: VideoOut | None = None
        if job.video:
            v = job.video
            video_out = VideoOut(
                title=v.title,
                channel=v.channel,
                duration_seconds=v.duration_seconds,
                upload_date=v.upload_date,
                thumbnail_url=v.thumbnail_url,
                has_captions=v.has_captions,
            )

        transcript_out: TranscriptOut | None = None
        tr = session.query(TranscriptModel).filter(TranscriptModel.job_id == job_id).first()
        if tr:
            transcript_out = TranscriptOut(
                source=tr.source,
                text=tr.text,
                model=tr.model,
                language=tr.language,
            )

        albums = [_album_out(a) for a in job.albums]

        return JobDetailOut(
            id=job.id,
            url=job.url,
            video_id=job.video_id,
            status=job.status,  # type: ignore[arg-type]
            status_detail=job.status_detail,
            error_message=job.error_message,
            warnings=job.warnings,
            created_at=job.created_at,
            updated_at=job.updated_at,
            video=video_out,
            transcript=transcript_out,
            albums=albums,
        )


@router.patch("/{job_id}/albums/{album_id}", response_model=AlbumRowOut)
def patch_album(job_id: str, album_id: str, body: PatchAlbumRequest) -> AlbumRowOut:
    with SessionLocal() as session:
        row = (
            session.query(AlbumRowModel)
            .filter(AlbumRowModel.job_id == job_id, AlbumRowModel.id == album_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Album not found")
        if body.selected and not row.on_spotify:
            raise HTTPException(
                status_code=400,
                detail="Cannot select an album that is not on Spotify",
            )
        row.selected = body.selected
        session.commit()
        session.refresh(row)
        return _album_out(row)