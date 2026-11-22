"""Create Spotify playlists from ticked album rows (user access token)."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from app.models import AlbumRowModel, JobModel, SessionLocal
from app.spotify_auth import get_user_id, get_valid_access_token

logger = logging.getLogger(__name__)

SPOTIFY_API = "https://api.spotify.com/v1"
BATCH_SIZE = 100


@dataclass
class PlaylistBuildResult:
    playlist_id: str
    playlist_url: str
    track_count: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class SpotifyPlaylistClient:
    """Injectable Spotify user API client for playlist creation."""

    access_token: str
    user_id: str
    _http: httpx.Client | None = None
    album_tracks: dict[str, list[str]] | None = None
    created_playlists: list[dict[str, Any]] = field(default_factory=list)
    add_batches: list[list[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self._http is None:
            self._http = httpx.Client(timeout=60.0)

    def close(self) -> None:
        if self._http:
            self._http.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict | None = None,
        data: dict | None = None,
    ) -> httpx.Response:
        assert self._http is not None
        while True:
            resp = self._http.request(
                method, url, headers=self._headers(), json=json, params=params, data=data
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "1"))
                logger.warning("Spotify 429; sleeping %ss", wait)
                time.sleep(wait)
                continue
            return resp

    def create_private_playlist(self, name: str) -> tuple[str, str]:
        payload = {"name": name, "public": False, "description": "Created with overheardr"}
        url = f"{SPOTIFY_API}/users/{self.user_id}/playlists"
        resp = self._request("POST", url, json=payload)
        resp.raise_for_status()
        body = resp.json()
        pid = body["id"]
        pl_url = body.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{pid}")
        self.created_playlists.append({"name": name, "id": pid, "public": False})
        return pid, pl_url

    def fetch_album_track_uris(self, album_id: str) -> list[str]:
        if self.album_tracks is not None and album_id in self.album_tracks:
            return list(self.album_tracks[album_id])

        uris: list[str] = []
        offset = 0
        limit = 50
        while True:
            resp = self._request(
                "GET",
                f"{SPOTIFY_API}/albums/{album_id}/tracks",
                params={"limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("items", []):
                uris.append(item["uri"])
            if body.get("next") is None:
                break
            offset += limit
        return uris

    def add_tracks(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), BATCH_SIZE):
            batch = uris[i : i + BATCH_SIZE]
            self.add_batches.append(list(batch))
            resp = self._request(
                "POST",
                f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
                json={"uris": batch},
            )
            resp.raise_for_status()


def build_client_from_session(
    *,
    token_getter: Callable[[], str | None] | None = None,
    user_id: str | None = None,
    album_tracks: dict[str, list[str]] | None = None,
) -> SpotifyPlaylistClient | None:
    access = token_getter() if token_getter else get_valid_access_token()
    uid = user_id or get_user_id()
    if not access or not uid:
        return None
    return SpotifyPlaylistClient(access_token=access, user_id=uid, album_tracks=album_tracks)


def create_job_playlist(
    job_id: str,
    playlist_name: str,
    *,
    client: SpotifyPlaylistClient | None = None,
) -> PlaylistBuildResult:
    with SessionLocal() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise ValueError("Job not found")
        rows = [
            r
            for r in job.albums
            if r.selected and r.on_spotify and r.spotify_album_id
        ]

    if not rows:
        raise ValueError("No ticked albums on Spotify")

    pl_client = client or build_client_from_session()
    if not pl_client:
        raise PermissionError("Spotify not connected")

    warnings: list[str] = []
    all_uris: list[str] = []

    try:
        playlist_id, playlist_url = pl_client.create_private_playlist(playlist_name)
        for row in rows:
            try:
                uris = pl_client.fetch_album_track_uris(row.spotify_album_id)
                all_uris.extend(uris)
            except Exception as exc:
                msg = f"Could not load tracks for {row.artist} – {row.album}: {exc}"
                logger.warning(msg)
                warnings.append(msg)

        if not all_uris:
            raise ValueError("No tracks could be added from the selected albums")

        pl_client.add_tracks(playlist_id, all_uris)

        with SessionLocal() as session:
            job = session.get(JobModel, job_id)
            if job:
                job.status = "done"
                job.playlist_id = playlist_id
                job.playlist_url = playlist_url
                job.playlist_name = playlist_name
                for w in warnings:
                    job.add_warning(w)
                session.commit()

        return PlaylistBuildResult(
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            track_count=len(all_uris),
            warnings=warnings,
        )
    finally:
        if client is None and pl_client:
            pl_client.close()