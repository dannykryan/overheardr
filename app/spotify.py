"""Spotify album search and fuzzy scoring (SPEC §8)."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from rapidfuzz import fuzz

from app.config import settings
from app.extraction_types import ExtractedAlbum
from app.models import SearchCacheModel, SessionLocal
from app.normalize import normalize

logger = logging.getLogger(__name__)

SPOTIFY_API = "https://api.spotify.com/v1"

ARTIST_SYNONYMS: dict[str, list[str]] = {
    "seatbelts": ["seat belts", "yoko kanno", "the seatbelts", "yoko kanno & the seatbelts"],
    "the dave brubeck quartet": ["dave brubeck", "dave brubeck quartet"],
    "carlos santana & john mclaughlin": ["mahavishnu orchestra", "santana", "john mclaughlin"],
    "tears for fears": ["tears for fears"],
}

ALBUM_SCORE_MIN = 85
ARTIST_SCORE_MIN = 80
ARTIST_SCORE_RELAXED = 70


@dataclass
class SpotifyMatch:
    on_spotify: bool
    spotify_album_id: str | None = None
    spotify_url: str | None = None
    spotify_album_name: str | None = None
    spotify_artist_name: str | None = None
    match_score: float | None = None
    cover_url: str | None = None


@dataclass
class SpotifySearchHit:
    id: str
    name: str
    artists: list[str]
    release_date: str
    album_type: str
    images: list[dict[str, Any]]
    external_urls: dict[str, str]


def _artist_variants(artist: str) -> list[str]:
    base = normalize(artist)
    variants = [artist]
    for key, syns in ARTIST_SYNONYMS.items():
        if base == key or base in [normalize(s) for s in syns]:
            variants.extend(syns)
            variants.append(key)
    return list(dict.fromkeys(variants))


def _cache_get(key: str) -> list[SpotifySearchHit] | None:
    with SessionLocal() as session:
        row = session.get(SearchCacheModel, key)
        if not row or row.provider != "spotify":
            return None
        data = json.loads(row.response_json)
        return [_hit_from_json(h) for h in data]


def _cache_set(key: str, hits: list[SpotifySearchHit]) -> None:
    payload = [h.__dict__ for h in hits]
    with SessionLocal() as session:
        row = session.get(SearchCacheModel, key)
        if row:
            row.response_json = json.dumps(payload)
        else:
            session.add(
                SearchCacheModel(
                    cache_key=key,
                    provider="spotify",
                    response_json=json.dumps(payload),
                )
            )
        session.commit()


def _hit_from_json(h: dict[str, Any]) -> SpotifySearchHit:
    return SpotifySearchHit(
        id=h["id"],
        name=h["name"],
        artists=h.get("artists", []),
        release_date=h.get("release_date", ""),
        album_type=h.get("album_type", "album"),
        images=h.get("images", []),
        external_urls=h.get("external_urls", {}),
    )


def _parse_spotify_items(items: list[dict[str, Any]]) -> list[SpotifySearchHit]:
    hits: list[SpotifySearchHit] = []
    for item in items:
        if item.get("type") != "album" and "album_type" not in item:
            continue
        hits.append(
            SpotifySearchHit(
                id=item["id"],
                name=item.get("name", ""),
                artists=[a.get("name", "") for a in item.get("artists", [])],
                release_date=item.get("release_date", ""),
                album_type=item.get("album_type", "album"),
                images=item.get("images", []),
                external_urls=item.get("external_urls", {}),
            )
        )
    return hits


class SpotifyClient:
    """Search Spotify Web API (client credentials or injected responses)."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        client_id: str | None = None,
        search_fn: Any | None = None,
    ):
        self._client = client or httpx.Client(timeout=30.0)
        self._client_id = client_id if client_id is not None else settings.spotify_client_id
        self._search_fn = search_fn
        self._token: str | None = None

    def search(self, query: str, limit: int = 10) -> list[SpotifySearchHit]:
        cache_key = f"spotify:{normalize(query)}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        if self._search_fn:
            items = self._search_fn(query)
            if not items:
                _cache_set(cache_key, [])
                return []
            if items and isinstance(items[0], dict) and isinstance(
                items[0].get("artists"), list
            ) and items[0]["artists"] and isinstance(items[0]["artists"][0], str):
                hits = [_hit_from_json(i) for i in items]
            else:
                hits = _parse_spotify_items(items)
            _cache_set(cache_key, hits)
            return hits

        if not self._client_id:
            return []

        items = self._api_search(query, limit=limit)
        hits = _parse_spotify_items(items)
        _cache_set(cache_key, hits)
        return hits

    def _api_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        token = self._get_client_credentials_token()
        if not token:
            return []
        resp = self._client.get(
            f"{SPOTIFY_API}/search",
            params={"q": query, "type": "album", "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "1"))
            logger.warning("Spotify 429; retry after %s", retry)
            return []
        resp.raise_for_status()
        return resp.json().get("albums", {}).get("items", [])

    def _get_client_credentials_token(self) -> str | None:
        if self._token:
            return self._token
        return None


def _year_bonus(hit_year: str, want_year: int | None) -> float:
    if not want_year or not hit_year:
        return 0.0
    try:
        hy = int(hit_year[:4])
    except ValueError:
        return 0.0
    if abs(hy - want_year) <= 1:
        return 3.0
    if "remaster" in hit_year.lower():
        return 1.0
    return 0.0


def _score_hit(
    hit: SpotifySearchHit,
    artist: str,
    album: str,
    year: int | None,
    alternate_titles: list[str],
) -> tuple[float, float, float]:
    title_candidates = [album] + alternate_titles
    best_album = 0.0
    for t in title_candidates:
        best_album = max(best_album, fuzz.token_set_ratio(normalize(t), normalize(hit.name)))

    artist_variants = _artist_variants(artist)
    best_artist = 0.0
    for av in artist_variants:
        for ha in hit.artists:
            best_artist = max(best_artist, fuzz.token_set_ratio(normalize(av), normalize(ha)))

    bonus = 0.0
    if hit.album_type == "album":
        bonus += 2.0
    elif hit.album_type in ("compilation", "single"):
        bonus -= 5.0
    bonus += _year_bonus(hit.release_date, year)
    if "netflix" in hit.name.lower() and "1998" not in hit.release_date[:4]:
        bonus -= 10.0

    total = (best_album + best_artist) / 2 + bonus
    return best_album, best_artist, total


def match_album(
    album: ExtractedAlbum,
    client: SpotifyClient,
) -> SpotifyMatch:
    """Search sequence from SPEC §8."""
    titles = [album.album] + list(album.alternate_titles)
    artists = _artist_variants(album.artist)

    best: tuple[float, SpotifySearchHit, float, float] | None = None

    for art in artists:
        for title in titles:
            queries = [
                f'album:"{title}" artist:"{art}"',
                f'"{title}" "{art}"',
            ]
            for q in queries:
                for hit in client.search(q):
                    ascore, arscore, total = _score_hit(
                        hit, album.artist, title, album.year, album.alternate_titles
                    )
                    if best is None or total > best[0]:
                        best = (total, hit, ascore, arscore)

    if best is None:
        return SpotifyMatch(on_spotify=False)

    _, hit, ascore, arscore = best
    exact_title = normalize(album.album) == normalize(hit.name) or any(
        normalize(a) == normalize(hit.name) for a in album.alternate_titles
    )
    accepted = (
        ascore >= ALBUM_SCORE_MIN and arscore >= ARTIST_SCORE_MIN
    ) or (exact_title and arscore >= ARTIST_SCORE_RELAXED)

    if not accepted:
        return SpotifyMatch(on_spotify=False, match_score=best[0])

    cover = hit.images[0]["url"] if hit.images else None
    return SpotifyMatch(
        on_spotify=True,
        spotify_album_id=hit.id,
        spotify_url=hit.external_urls.get("spotify"),
        spotify_album_name=hit.name,
        spotify_artist_name=", ".join(hit.artists),
        match_score=best[0],
        cover_url=cover,
    )


def match_with_canned_responses(
    album: ExtractedAlbum,
    responses: dict[str, list[dict[str, Any]]],
) -> SpotifyMatch:
    """Match using a query→items map (offline tests)."""

    def search_fn(query: str) -> list[dict[str, Any]]:
        nq = normalize(query)
        direct = responses.get(f"{album.artist}::{album.album}")
        if direct is not None:
            return direct
        for key, items in responses.items():
            if normalize(key) in nq or key.lower() in query.lower():
                return items
        return responses.get("*", [])

    client = SpotifyClient(search_fn=search_fn)
    return match_album(album, client)