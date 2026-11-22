"""Pydantic schemas for JSON API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal[
    "queued",
    "fetching",
    "transcribing",
    "extracting",
    "matching",
    "ready",
    "creating_playlist",
    "done",
    "error",
]


class CreateJobRequest(BaseModel):
    url: str


class CreateJobResponse(BaseModel):
    id: str
    status: JobStatus


class TranscriptOut(BaseModel):
    source: str
    text: str | None = None
    model: str | None = None
    language: str | None = None


class VideoOut(BaseModel):
    title: str | None = None
    channel: str | None = None
    duration_seconds: int | None = None
    upload_date: str | None = None
    thumbnail_url: str | None = None
    has_captions: bool = False


class AlbumRowOut(BaseModel):
    id: str
    artist: str
    album: str
    year: int | None = None
    alternate_titles: list[str] = Field(default_factory=list)
    role: str
    sources: list[str] = Field(default_factory=list)
    confidence: str
    evidence: str | None = None
    speaker: str | None = None
    selected: bool
    on_spotify: bool
    spotify_album_id: str | None = None
    spotify_url: str | None = None
    spotify_album_name: str | None = None
    spotify_artist_name: str | None = None
    match_score: float | None = None
    cover_url: str | None = None
    musicbrainz_release_group_id: str | None = None
    unavailable_reason: str | None = None


class JobDetailOut(BaseModel):
    id: str
    url: str
    video_id: str | None = None
    status: JobStatus
    status_detail: str | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    video: VideoOut | None = None
    transcript: TranscriptOut | None = None
    albums: list[AlbumRowOut] = Field(default_factory=list)


class PatchAlbumRequest(BaseModel):
    selected: bool