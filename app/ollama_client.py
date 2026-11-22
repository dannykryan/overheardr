"""Ollama HTTP gap-fill client (SPEC §6.2)."""

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.extraction_types import Confidence, ExtractedAlbum, Role, Source

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract music albums from a YouTube video transcript.
Return ONLY valid JSON that matches this schema, with no markdown fences:
{
  "albums": [
    {
      "artist": "string",
      "album": "string",
      "year": 1983,
      "alternate_titles": ["string"],
      "role": "bag_pick" | "mention",
      "confidence": "high" | "medium" | "low",
      "evidence": "short quote from the transcript",
      "speaker": "string or null"
    }
  ]
}
Rules:
- Do not invent albums that the transcript does not support.
- role=bag_pick only when someone is presenting a record they picked or have in the bag.
- role=mention for albums cited in passing (influences, earlier records, the band's own catalogue, something shown on a nearby sleeve).
- Prefer the official album title, not a track name mentioned while showing the sleeve.
- If you know a native-script or alternate official title, put it in alternate_titles (example: Yukihiro Takahashi's "Tomorrow's Just Another Day" is also 薔薇色の明日).
- year may be null if not stated. Do not guess wildly.
- If the speech is garbled, still emit your best reading at confidence=low rather than dropping a clearly presented pick."""

NUM_CTX = 4096
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 400


class OllamaError(Exception):
    pass


def _chunk_transcript(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + CHUNK_CHARS // 2:
                end = boundary
        chunks.append(text[start:end])
        start = max(end - CHUNK_OVERLAP, end)
    return chunks


def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    albums = data.get("albums", [])
    if not isinstance(albums, list):
        raise OllamaError("Invalid albums key")
    return albums


def _to_extracted(items: list[dict[str, Any]]) -> list[ExtractedAlbum]:
    out: list[ExtractedAlbum] = []
    for item in items:
        role: Role = item.get("role", "mention")
        if role not in ("bag_pick", "mention"):
            role = "mention"
        conf: Confidence = item.get("confidence", "medium")
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        year = item.get("year")
        if year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None
        alts = item.get("alternate_titles") or []
        if not isinstance(alts, list):
            alts = []
        out.append(
            ExtractedAlbum(
                artist=str(item.get("artist", "")).strip(),
                album=str(item.get("album", "")).strip(),
                year=year,
                alternate_titles=[str(a) for a in alts],
                role=role,
                confidence=conf,
                sources=["transcript_llm"],
                evidence=item.get("evidence"),
                speaker=item.get("speaker"),
            )
        )
    return [a for a in out if a.artist and a.album]


def _user_message(
    video_title: str,
    description_albums: list[ExtractedAlbum],
    transcript_chunk: str,
) -> str:
    desc_lines = [
        f"- {a.artist} - {a.album}" for a in description_albums
    ]
    return (
        f"Video title: {video_title}\n\n"
        f"Already parsed from description:\n"
        + ("\n".join(desc_lines) if desc_lines else "(none)")
        + f"\n\nTranscript segment:\n{transcript_chunk}"
    )


async def extract_from_transcript(
    video_title: str,
    description_albums: list[ExtractedAlbum],
    transcript: str,
    *,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> list[ExtractedAlbum]:
    """Run Ollama gap-fill; empty list on failure (caller adds warning)."""
    base = base_url or settings.ollama_base_url
    model_name = model or settings.ollama_model
    chunks = _chunk_transcript(transcript)
    all_items: list[dict[str, Any]] = []
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=120.0)

    assert client is not None
    try:
        for chunk in chunks:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _user_message(video_title, description_albums, chunk),
                    },
                ],
                "stream": False,
                "options": {"temperature": 0, "num_ctx": NUM_CTX},
                "format": "json",
            }
            resp = await client.post(f"{base}/api/chat", json=payload)
            resp.raise_for_status()
            body = resp.json()
            content = body.get("message", {}).get("content", "")
            all_items.extend(_parse_llm_json(content))
    finally:
        if own_client:
            await client.aclose()

    return _to_extracted(all_items)


def extract_from_transcript_sync(
    video_title: str,
    description_albums: list[ExtractedAlbum],
    transcript: str,
    *,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> list[ExtractedAlbum]:
    base = base_url or settings.ollama_base_url
    model_name = model or settings.ollama_model
    chunks = _chunk_transcript(transcript)
    all_items: list[dict[str, Any]] = []
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=120.0)

    assert client is not None
    try:
        for chunk in chunks:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _user_message(video_title, description_albums, chunk),
                    },
                ],
                "stream": False,
                "options": {"temperature": 0, "num_ctx": NUM_CTX},
                "format": "json",
            }
            resp = client.post(f"{base}/api/chat", json=payload)
            resp.raise_for_status()
            body = resp.json()
            content = body.get("message", {}).get("content", "")
            all_items.extend(_parse_llm_json(content))
    finally:
        if own_client:
            client.close()

    return _to_extracted(all_items)