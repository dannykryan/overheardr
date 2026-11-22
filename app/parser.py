"""Deterministic description-list parser (SPEC §6.1)."""

import re

from app.extraction_types import ExtractedAlbum

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[•\-*·]|\d+[.)]\s*)(.+)$",
)
_DASH_SPLIT = re.compile(r"\s+[-–—]\s+")
_FORMAT_TAG_RE = re.compile(
    r"\s*\((?:CD|LP|vinyl|cassette|2xLP|2LP)\)\s*$",
    re.IGNORECASE,
)
_TRAILING_OST_BRACKET_RE = re.compile(r"\s*\[OST\]\s*$", re.IGNORECASE)
_URL_RE = re.compile(r"https?://", re.I)
_PICKS_HEADING_RE = re.compile(r"picks|albums|tracklist", re.I)


def _strip_format_tags(line: str) -> tuple[str, list[str]]:
    """Remove (CD)/(LP) suffixes; keep [OST] as part of title when present."""
    alternates: list[str] = []
    m = _TRAILING_OST_BRACKET_RE.search(line)
    if m:
        base = _TRAILING_OST_BRACKET_RE.sub("", line).strip()
        alternates.append(f"{base} (Original Soundtrack)")
    line = _FORMAT_TAG_RE.sub("", line)
    line = line.strip()
    return line, alternates


def _parse_item_body(body: str) -> ExtractedAlbum | None:
    body = body.strip()
    if not body or _URL_RE.search(body):
        return None
    parts = _DASH_SPLIT.split(body, maxsplit=1)
    if len(parts) != 2:
        return None
    artist, album = parts[0].strip(), parts[1].strip()
    album, extra_alts = _strip_format_tags(album)
    if not artist or not album:
        return None
    if "[OST]" in body and "(Original Soundtrack)" not in album:
        album = re.sub(r"\s*\[OST\]\s*", " (Original Soundtrack)", album).strip()
    return ExtractedAlbum(
        artist=artist,
        album=album,
        alternate_titles=extra_alts,
        role="bag_pick",
        confidence="high",
        sources=["description"],
    )


def parse_description(description: str) -> list[ExtractedAlbum]:
    """Return bag picks from bullet/numbered lists in a video description."""
    lines = description.splitlines()
    in_picks = False
    results: list[ExtractedAlbum] = []

    for line in lines:
        stripped = line.strip()
        if _PICKS_HEADING_RE.search(stripped) and "http" not in stripped.lower():
            in_picks = True
            continue

        m = _LIST_ITEM_RE.match(line)
        if not m:
            if in_picks and stripped == "":
                continue
            if in_picks and not stripped.startswith("•"):
                if stripped.startswith("👉") or stripped.startswith("#"):
                    break
            continue

        if not in_picks and not _PICKS_HEADING_RE.search(description):
            in_picks = True

        row = _parse_item_body(m.group(1))
        if row:
            results.append(row)

    if not results:
        for line in lines:
            m = _LIST_ITEM_RE.match(line)
            if m:
                row = _parse_item_body(m.group(1))
                if row:
                    results.append(row)

    return results