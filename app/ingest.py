"""yt-dlp metadata, captions, and whisper transcription."""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

YTDLP_REMOTE_COMPONENTS = ["ejs:github"]


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    upload_date: str | None
    description: str
    thumbnail_url: str | None
    has_captions: bool
    info: dict[str, Any]


@dataclass
class TranscriptResult:
    source: str
    text: str
    timed_text: str | None = None
    model: str | None = None
    language: str | None = None
    audio_path: str | None = None


def _video_cache_dir(video_id: str) -> Path:
    d = settings.cache_dir / "videos" / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _strip_bulky_info(info: dict[str, Any]) -> dict[str, Any]:
    out = dict(info)
    for key in ("formats", "heatmap", "thumbnails"):
        out.pop(key, None)
    return out


def fetch_metadata_ytdlp(url: str, video_id: str) -> VideoMetadata:
    """Fetch metadata via yt-dlp Python API."""
    import yt_dlp

    cache = _video_cache_dir(video_id)
    info_path = cache / "info.json"

    ydl_opts = {
        "skip_download": True,
        "writeinfojson": True,
        "remote_components": YTDLP_REMOTE_COMPONENTS,
        "outtmpl": str(cache / "%(id)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    clean = _strip_bulky_info(info)
    info_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    has_captions = bool(subs or auto)

    return VideoMetadata(
        video_id=video_id,
        title=info.get("title") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        duration_seconds=int(info.get("duration") or 0),
        upload_date=info.get("upload_date"),
        description=info.get("description") or "",
        thumbnail_url=info.get("thumbnail"),
        has_captions=has_captions,
        info=clean,
    )


def fetch_metadata_from_fixture(video_id: str, fixture_info_path: Path, description: str | None = None) -> VideoMetadata:
    """Load metadata from a committed fixture file (tests)."""
    info = json.loads(fixture_info_path.read_text(encoding="utf-8"))
    desc = description if description is not None else (info.get("description") or "")
    return VideoMetadata(
        video_id=video_id,
        title=info.get("title") or "",
        channel=info.get("channel") or "",
        duration_seconds=int(info.get("duration") or 0),
        upload_date=info.get("upload_date"),
        description=desc,
        thumbnail_url=info.get("thumbnail"),
        has_captions=bool(info.get("subtitles") or info.get("automatic_captions")),
        info=info,
    )


def load_cached_transcript(video_id: str) -> TranscriptResult | None:
    cache = _video_cache_dir(video_id)
    text_path = cache / f"{video_id}.txt"
    if text_path.exists():
        text = text_path.read_text(encoding="utf-8")
        ts_path = cache / f"{video_id}_timestamps.txt"
        timed = ts_path.read_text(encoding="utf-8") if ts_path.exists() else None
        meta_path = cache / "transcript_meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return TranscriptResult(
            source=meta.get("source", "whisper"),
            text=text,
            timed_text=timed,
            model=meta.get("model"),
            language=meta.get("language"),
            audio_path=meta.get("audio_path"),
        )
    return None


def save_transcript_cache(video_id: str, result: TranscriptResult) -> None:
    cache = _video_cache_dir(video_id)
    (cache / f"{video_id}.txt").write_text(result.text, encoding="utf-8")
    if result.timed_text:
        (cache / f"{video_id}_timestamps.txt").write_text(result.timed_text, encoding="utf-8")
    meta = {
        "source": result.source,
        "model": result.model,
        "language": result.language,
        "audio_path": result.audio_path,
    }
    (cache / "transcript_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def transcribe_with_whisper(
    video_id: str,
    url: str,
    *,
    transcriber: Callable[[Path], tuple[str, str | None]] | None = None,
) -> TranscriptResult:
    """Download audio and transcribe with faster-whisper (or injected transcriber)."""
    cache = _video_cache_dir(video_id)
    audio_path = cache / f"{video_id}.m4a"

    if not audio_path.exists():
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(cache / f"{video_id}.%(ext)s"),
            "remote_components": YTDLP_REMOTE_COMPONENTS,
            "quiet": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"},
            ],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    if transcriber:
        text, timed = transcriber(audio_path)
        result = TranscriptResult(
            source="whisper",
            text=text,
            timed_text=timed,
            model=settings.whisper_model,
            language="en",
            audio_path=str(audio_path),
        )
    else:
        from faster_whisper import WhisperModel

        settings.whisper_models_dir.mkdir(parents=True, exist_ok=True)
        model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type=settings.whisper_compute_type,
            download_root=str(settings.whisper_models_dir),
        )
        segments, info = model.transcribe(str(audio_path), beam_size=5)
        lines: list[str] = []
        timed_lines: list[str] = []
        for seg in segments:
            lines.append(seg.text.strip())
            timed_lines.append(f"[{seg.start:.2f} -> {seg.end:.2f}] {seg.text.strip()}")
        result = TranscriptResult(
            source="whisper",
            text="\n".join(lines),
            timed_text="\n".join(timed_lines),
            model=settings.whisper_model,
            language=getattr(info, "language", None),
            audio_path=str(audio_path),
        )

    save_transcript_cache(video_id, result)
    return result


def load_fixture_transcript(fixture_dir: Path, video_id: str) -> TranscriptResult:
    text = (fixture_dir / f"{video_id}.txt").read_text(encoding="utf-8")
    ts_path = fixture_dir / f"{video_id}_timestamps.txt"
    timed = ts_path.read_text(encoding="utf-8") if ts_path.exists() else None
    return TranscriptResult(
        source="whisper",
        text=text,
        timed_text=timed,
        model=settings.whisper_model,
        language="en",
    )


def deno_available() -> bool:
    try:
        subprocess.run(["deno", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False