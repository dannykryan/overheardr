"""Spotify session required for live matching (offline)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import JobModel, SessionLocal
from app.pipeline import SPOTIFY_LOGIN_WARNING, rematch_spotify, run_pipeline
from app.services import PipelineServices, set_services

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "TtDMUz6TBIc"


def test_pipeline_warns_when_spotify_not_connected() -> None:
    svc = PipelineServices(fixture_dir=FIXTURE_DIR, skip_transcribe=True)
    set_services(svc)
    url = "https://www.youtube.com/watch?v=TtDMUz6TBIc"
    with SessionLocal() as session:
        job = JobModel(url=url, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    run_pipeline(job_id, svc)

    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert any(SPOTIFY_LOGIN_WARNING in w for w in detail["warnings"])
    assert all(a["unavailable_reason"] == "Spotify login required to search" for a in detail["albums"])


def test_rematch_uses_user_token_after_login(
    acceptance_spotify_responses: dict,
    monkeypatch,
) -> None:
    svc = PipelineServices(fixture_dir=FIXTURE_DIR, skip_transcribe=True)
    set_services(svc)
    url = "https://www.youtube.com/watch?v=TtDMUz6TBIc"
    with SessionLocal() as session:
        job = JobModel(url=url, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    run_pipeline(job_id, svc)

    def fake_token() -> str:
        return "logged-in-token"

    monkeypatch.setattr("app.pipeline.get_valid_access_token", fake_token)
    monkeypatch.setattr("app.spotify.get_valid_access_token", fake_token)

    captured: list[str] = []

    def search_fn(query: str) -> list[dict]:
        captured.append(query)
        key = next(iter(acceptance_spotify_responses))
        return acceptance_spotify_responses[key]

    from app.spotify import SpotifyClient

    rematch_svc = PipelineServices(
        fixture_dir=FIXTURE_DIR,
        skip_transcribe=True,
        spotify_client=SpotifyClient(search_fn=search_fn, access_token="logged-in-token"),
    )
    rematch_spotify(job_id, rematch_svc)

    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert captured, "rematch should invoke Spotify search"
    assert not any(SPOTIFY_LOGIN_WARNING in w for w in detail["warnings"])
    on_spotify = [a for a in detail["albums"] if a["on_spotify"]]
    assert len(on_spotify) >= 1