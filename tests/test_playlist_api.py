"""Playlist creation API tests (mocked Spotify)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import SpotifySessionModel, SessionLocal
from app.spotify_playlist import SpotifyPlaylistClient, create_job_playlist
from tests.test_pipeline_api import _run_fixture_pipeline


def _seed_spotify_session() -> None:
    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, 1)
        if not row:
            row = SpotifySessionModel(id=1)
            session.add(row)
        row.access_token = "test-token"
        row.refresh_token = "test-refresh"
        row.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        row.user_id = "spotify-user"
        row.display_name = "Tester"
        session.commit()


def test_playlist_uses_ticked_albums_in_order(acceptance_spotify_responses: dict) -> None:
    job_id = _run_fixture_pipeline(acceptance_spotify_responses)
    _seed_spotify_session()

    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    selected_rows = [
        a for a in detail["albums"] if a["selected"] and a["on_spotify"] and a["spotify_album_id"]
    ]
    assert len(selected_rows) >= 19

    album_tracks = {
        row["spotify_album_id"]: [f"spotify:track:{row['spotify_album_id']}-t{i}" for i in range(2)]
        for row in selected_rows
    }

    pl_client = SpotifyPlaylistClient(
        access_token="test-token",
        user_id="spotify-user",
        album_tracks=album_tracks,
    )

    def _fake_create(name: str) -> tuple[str, str]:
        pl_client.created_playlists.append({"name": name, "id": "pl123", "public": False})
        return "pl123", "https://open.spotify.com/playlist/pl123"

    pl_client.create_private_playlist = _fake_create  # type: ignore[method-assign]

    def _fake_add(playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            pl_client.add_batches.append(uris[i : i + 100])

    pl_client.add_tracks = _fake_add  # type: ignore[method-assign]

    result = create_job_playlist(
        job_id,
        "Test Bag Playlist",
        client=pl_client,
    )
    assert result.track_count == len(selected_rows) * 2
    assert pl_client.created_playlists[0]["public"] is False

    expected_uris: list[str] = []
    for row in selected_rows:
        expected_uris.extend(album_tracks[row["spotify_album_id"]])
    flat_added = [u for batch in pl_client.add_batches for u in batch]
    assert flat_added == expected_uris

    detail2 = client.get(f"/api/jobs/{job_id}").json()
    assert detail2["playlist_url"]
    assert detail2["status"] == "done"


def test_playlist_400_when_nothing_ticked(acceptance_spotify_responses: dict) -> None:
    job_id = _run_fixture_pipeline(acceptance_spotify_responses)
    _seed_spotify_session()

    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    for album in detail["albums"]:
        if album["on_spotify"]:
            client.patch(
                f"/api/jobs/{job_id}/albums/{album['id']}",
                json={"selected": False},
            )

    resp = client.post(f"/api/jobs/{job_id}/playlist", json={"name": "Empty"})
    assert resp.status_code == 400


def test_get_job_after_fixture_ingest(acceptance_spotify_responses: dict, fixture_url: str) -> None:
    client = TestClient(app)
    create = client.post("/api/jobs", json={"url": fixture_url})
    assert create.status_code == 201
    job_id = create.json()["id"]

    from pathlib import Path

    from app.pipeline import run_pipeline
    from app.services import PipelineServices, get_services, set_services

    FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "TtDMUz6TBIc"
    set_services(
        PipelineServices(
            fixture_dir=FIXTURE_DIR,
            skip_transcribe=True,
            spotify_responses=acceptance_spotify_responses,
        )
    )
    run_pipeline(job_id, get_services())

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert len([a for a in detail["albums"] if a["role"] == "bag_pick"]) == 21