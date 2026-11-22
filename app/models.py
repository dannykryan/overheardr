"""SQLAlchemy models (SPEC §4)."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    video_id: Mapped[str | None] = mapped_column(String(11), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    playlist_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    playlist_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    playlist_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    video: Mapped["VideoModel | None"] = relationship(back_populates="job", uselist=False)
    transcript: Mapped["TranscriptModel | None"] = relationship(back_populates="job", uselist=False)
    albums: Mapped[list["AlbumRowModel"]] = relationship(
        back_populates="job", order_by="AlbumRowModel.sort_order"
    )

    @property
    def warnings(self) -> list[str]:
        return json.loads(self.warnings_json or "[]")

    def set_warnings(self, items: list[str]) -> None:
        self.warnings_json = json.dumps(items)

    def add_warning(self, msg: str) -> None:
        w = self.warnings
        if msg not in w:
            w.append(msg)
        self.set_warnings(w)


class VideoModel(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), unique=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_date: Mapped[str | None] = mapped_column(String(8), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_captions: Mapped[bool] = mapped_column(Boolean, default=False)
    info_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapters_json: Mapped[str] = mapped_column(Text, default="[]")

    job: Mapped[JobModel] = relationship(back_populates="video")


class TranscriptModel(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[JobModel] = relationship(back_populates="transcript")


class AlbumRowModel(Base):
    __tablename__ = "album_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    artist: Mapped[str] = mapped_column(Text, nullable=False)
    album: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alternate_titles_json: Mapped[str] = mapped_column(Text, default="[]")
    role: Mapped[str] = mapped_column(String(16), default="bag_pick")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(8), default="high")
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    on_spotify: Mapped[bool] = mapped_column(Boolean, default=False)
    spotify_album_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spotify_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_album_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_artist_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    musicbrainz_release_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[JobModel] = relationship(back_populates="albums")

    @property
    def alternate_titles(self) -> list[str]:
        return json.loads(self.alternate_titles_json or "[]")

    def set_alternate_titles(self, items: list[str]) -> None:
        self.alternate_titles_json = json.dumps(items)

    @property
    def sources(self) -> list[str]:
        return json.loads(self.sources_json or "[]")

    def set_sources(self, items: list[str]) -> None:
        self.sources_json = json.dumps(items)


class SearchCacheModel(Base):
    __tablename__ = "search_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


_engine = create_engine(
    f"sqlite:///{settings.data_dir / 'overheardr.db'}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)