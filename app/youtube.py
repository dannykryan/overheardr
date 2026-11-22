"""YouTube URL validation and video ID extraction."""

import re
from urllib.parse import parse_qs, urlparse

_YT_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Return an 11-character video ID or None if the URL is not YouTube."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host not in _YT_HOSTS:
        return None

    if host in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if _VIDEO_ID_RE.match(vid) else None

    if parsed.path.startswith("/shorts/"):
        vid = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
        return vid if _VIDEO_ID_RE.match(vid) else None

    if parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        vids = qs.get("v", [])
        if vids and _VIDEO_ID_RE.match(vids[0]):
            return vids[0]

    return None


def validate_youtube_url(url: str) -> str:
    """Validate URL and return video_id or raise ValueError."""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Invalid or non-YouTube URL")
    return video_id