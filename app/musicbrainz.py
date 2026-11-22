"""MusicBrainz alias lookup and Cover Art Archive URLs."""

import json
import logging
from typing import Any, Callable

import httpx

from app.models import SearchCacheModel, SessionLocal
from app.normalize import normalize, pair_key

logger = logging.getLogger(__name__)

MB_USER_AGENT = "overheardr/0.1 (local; personal-use)"
MB_API = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"


def _cache_get(key: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.get(SearchCacheModel, key)
        if not row or row.provider != "musicbrainz":
            return None
        return json.loads(row.response_json)


def _cache_set(key: str, data: dict[str, Any]) -> None:
    with SessionLocal() as session:
        row = session.get(SearchCacheModel, key)
        if row:
            row.response_json = json.dumps(data)
        else:
            session.add(
                SearchCacheModel(
                    cache_key=key,
                    provider="musicbrainz",
                    response_json=json.dumps(data),
                )
            )
        session.commit()


class MusicBrainzClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        lookup_fn: Callable[[str, str], dict[str, Any] | None] | None = None,
    ):
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": MB_USER_AGENT})
        self._lookup_fn = lookup_fn

    def release_group_aliases(self, artist: str, album: str) -> tuple[list[str], str | None, str | None]:
        """Return alias list, release-group id, cover art URL."""
        key = f"mb:{pair_key(artist, album)}"
        cached = _cache_get(key)
        if cached:
            return (
                cached.get("aliases", []),
                cached.get("release_group_id"),
                cached.get("cover_url"),
            )

        if self._lookup_fn:
            data = self._lookup_fn(artist, album) or {}
        else:
            data = self._api_lookup(artist, album)

        aliases = data.get("aliases", [])
        rg_id = data.get("release_group_id")
        cover = data.get("cover_url")
        if rg_id and not cover:
            cover = f"{CAA_BASE}/release-group/{rg_id}/front"

        _cache_set(key, {"aliases": aliases, "release_group_id": rg_id, "cover_url": cover})
        return aliases, rg_id, cover

    def _api_lookup(self, artist: str, album: str) -> dict[str, Any]:
        q = f'release-group:"{album}" AND artist:"{artist}"'
        resp = self._client.get(
            f"{MB_API}/release-group",
            params={"query": q, "fmt": "json", "limit": 3},
        )
        if resp.status_code != 200:
            return {}
        groups = resp.json().get("release-groups", [])
        if not groups:
            return {}
        rg = groups[0]
        rg_id = rg.get("id")
        aliases = [a.get("name") for a in rg.get("aliases", []) if a.get("name")]
        return {"aliases": aliases, "release_group_id": rg_id, "cover_url": None}