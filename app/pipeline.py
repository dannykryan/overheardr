"""Background job pipeline: ingest → transcribe → extract → match."""

import logging
from datetime import datetime, timezone

from app.extraction_types import ExtractedAlbum
from app.ingest import (
    TranscriptResult,
    load_cached_transcript,
    load_fixture_transcript,
    save_transcript_cache,
    transcribe_with_whisper,
)
from app.merge import merge_albums
from app.models import AlbumRowModel, JobModel, SessionLocal, TranscriptModel, VideoModel
from app.musicbrainz import MusicBrainzClient
from app.ollama_client import OllamaError, extract_from_transcript_sync
from app.parser import parse_description
from app.services import PipelineServices, get_services
from app.spotify import SpotifyClient, SpotifyMatch, match_album, match_with_canned_responses
from app.youtube import validate_youtube_url

logger = logging.getLogger(__name__)


def _set_status(job_id: str, status: str, detail: str | None = None) -> None:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            return
        job.status = status
        job.status_detail = detail
        job.updated_at = datetime.now(timezone.utc)
        session.commit()


def _fail_job(job_id: str, message: str) -> None:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            return
        job.status = "error"
        job.error_message = message
        job.updated_at = datetime.now(timezone.utc)
        session.commit()


def _add_warning(job_id: str, msg: str) -> None:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if job:
            job.add_warning(msg)
            job.updated_at = datetime.now(timezone.utc)
            session.commit()


def _extracted_to_row(
    ext: ExtractedAlbum,
    sort_order: int,
    match: SpotifyMatch,
    *,
    mb_cover: str | None,
    mb_id: str | None,
) -> AlbumRowModel:
    on_sp = match.on_spotify
    if ext.role == "mention":
        selected = False
    elif ext.role == "bag_pick" and ext.confidence == "low" and ext.sources == ["transcript_llm"]:
        selected = on_sp
    else:
        selected = on_sp and ext.role == "bag_pick"

    cover = match.cover_url or mb_cover
    row = AlbumRowModel(
        sort_order=sort_order,
        artist=ext.artist,
        album=ext.album,
        year=ext.year,
        role=ext.role,
        confidence=ext.confidence,
        evidence=ext.evidence,
        speaker=ext.speaker,
        selected=selected,
        on_spotify=on_sp,
        spotify_album_id=match.spotify_album_id,
        spotify_url=match.spotify_url,
        spotify_album_name=match.spotify_album_name,
        spotify_artist_name=match.spotify_artist_name,
        match_score=match.match_score,
        cover_url=cover,
        musicbrainz_release_group_id=mb_id,
        unavailable_reason=None if on_sp else "No confident Spotify match",
    )
    row.set_alternate_titles(ext.alternate_titles)
    row.set_sources(ext.sources)
    return row


def _match_rows(
    merged: list[ExtractedAlbum],
    services: PipelineServices,
) -> list[AlbumRowModel]:
    mb = services.musicbrainz_client or MusicBrainzClient()
    rows: list[AlbumRowModel] = []

    for i, ext in enumerate(merged):
        if services.spotify_responses:
            match = match_with_canned_responses(ext, services.spotify_responses)
        elif services.spotify_client:
            match = match_album(ext, services.spotify_client)
        else:
            match = match_album(ext, SpotifyClient())

        aliases, rg_id, cover = mb.release_group_aliases(ext.artist, ext.album)
        for alias in aliases:
            if alias not in ext.alternate_titles:
                ext.alternate_titles.append(alias)

        if not match.on_spotify and aliases:
            if services.spotify_responses:
                match = match_with_canned_responses(ext, services.spotify_responses)
            elif services.spotify_client:
                match = match_album(ext, services.spotify_client)
            else:
                match = match_album(ext, SpotifyClient())

        rows.append(_extracted_to_row(ext, i, match, mb_cover=cover, mb_id=rg_id))
    return rows


def run_pipeline(job_id: str, services: PipelineServices | None = None) -> None:
    services = services or get_services()
    try:
        with SessionLocal() as session:
            job = session.get(JobModel, job_id)
            if not job:
                return
            url = job.url

        video_id = validate_youtube_url(url)
        with SessionLocal() as session:
            job = session.get(JobModel, job_id)
            if job:
                job.video_id = video_id
                session.commit()

        _set_status(job_id, "fetching", "Downloading metadata")
        meta = services.fetch_metadata(url, video_id)

        with SessionLocal() as session:
            job = session.get(JobModel, job_id)
            if not job:
                return
            session.add(
                VideoModel(
                    job_id=job_id,
                    title=meta.title,
                    channel=meta.channel,
                    duration_seconds=meta.duration_seconds,
                    upload_date=meta.upload_date,
                    description=meta.description,
                    thumbnail_url=meta.thumbnail_url,
                    has_captions=meta.has_captions,
                    info_json_path=(
                        str(services.fixture_dir / "info.json") if services.fixture_dir else None
                    ),
                    chapters_json="[]",
                )
            )
            session.commit()

        _set_status(job_id, "transcribing", "Captions or whisper")
        transcript = load_cached_transcript(video_id)
        if transcript is None:
            if services.fixture_dir:
                transcript = load_fixture_transcript(services.fixture_dir, video_id)
                save_transcript_cache(video_id, transcript)
            elif meta.has_captions:
                transcript = TranscriptResult(source="captions", text="")
            elif services.skip_transcribe:
                raise RuntimeError("Transcript required but transcribe skipped")
            else:
                transcript = transcribe_with_whisper(video_id, url)

        with SessionLocal() as session:
            job = session.get(JobModel, job_id)
            if not job:
                return
            session.add(
                TranscriptModel(
                    job_id=job_id,
                    source=transcript.source,
                    text=transcript.text,
                    timed_text=transcript.timed_text,
                    model=transcript.model,
                    language=transcript.language,
                    audio_path=transcript.audio_path,
                )
            )
            session.commit()

        _set_status(job_id, "extracting", "Parsing description and transcript")
        desc_albums = parse_description(meta.description)
        llm_albums: list[ExtractedAlbum] = []

        transcript_for_llm = transcript.timed_text or transcript.text or ""

        if services.ollama_raises:
            _add_warning(job_id, "Ollama unavailable; used description only")
        elif services.ollama_invalid_json:
            _add_warning(job_id, "Ollama returned invalid JSON; used description only")
        elif services.ollama_fn:
            try:
                llm_albums = services.ollama_fn(meta.title, desc_albums, transcript_for_llm)
            except Exception:
                _add_warning(job_id, "Ollama unavailable; used description only")
        elif transcript_for_llm.strip():
            try:
                llm_albums = extract_from_transcript_sync(
                    meta.title, desc_albums, transcript_for_llm
                )
            except (OllamaError, Exception) as exc:
                logger.warning("Ollama gap-fill failed: %s", exc)
                _add_warning(job_id, "Ollama unavailable; used description only")

        merged = merge_albums(desc_albums, llm_albums)

        _set_status(job_id, "matching", "Spotify and covers")
        rows = _match_rows(merged, services)
        _save_albums(job_id, rows)
        _set_status(job_id, "ready", "Review")

    except ValueError as exc:
        _fail_job(job_id, str(exc))
    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job_id)
        _fail_job(job_id, str(exc))


def _save_albums(job_id: str, rows: list[AlbumRowModel]) -> None:
    with SessionLocal() as session:
        session.query(AlbumRowModel).filter(AlbumRowModel.job_id == job_id).delete()
        for row in rows:
            row.job_id = job_id
            session.add(row)
        session.commit()