"""Injectable service bundle for pipeline and tests."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.ingest import TranscriptResult, VideoMetadata, fetch_metadata_from_fixture, fetch_metadata_ytdlp
from app.musicbrainz import MusicBrainzClient
from app.spotify import SpotifyClient


MetadataFn = Callable[[str, str], VideoMetadata]
CaptionFn = Callable[[str, str, dict], TranscriptResult]


@dataclass
class PipelineServices:
    metadata_fn: MetadataFn | None = None
    fixture_dir: Path | None = None
    fixture_description: str | None = None
    skip_transcribe: bool = False
    caption_fn: CaptionFn | None = None
    spotify_client: SpotifyClient | None = None
    spotify_responses: dict[str, list[dict[str, Any]]] | None = None
    musicbrainz_client: MusicBrainzClient | None = None
    ollama_fn: Callable[..., list] | None = None
    ollama_raises: Exception | None = None
    ollama_invalid_json: bool = False

    def fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        if self.metadata_fn:
            return self.metadata_fn(url, video_id)
        if self.fixture_dir:
            info_path = self.fixture_dir / "info.json"
            return fetch_metadata_from_fixture(
                video_id, info_path, description=self.fixture_description
            )
        return fetch_metadata_ytdlp(url, video_id)


_default_services = PipelineServices()


def get_services() -> PipelineServices:
    return _default_services


def set_services(services: PipelineServices) -> None:
    global _default_services
    _default_services = services


def reset_services() -> None:
    global _default_services
    _default_services = PipelineServices()