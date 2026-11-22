"""POST /api/jobs schedules pipeline without duplicate work in unit tests."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import PipelineServices, set_services
from tests.conftest import FIXTURE_DIR


def test_post_job_returns_id_and_runs_to_ready(
    acceptance_spotify_responses: dict,
    fixture_url: str,
) -> None:
    svc = PipelineServices(
        fixture_dir=FIXTURE_DIR,
        skip_transcribe=True,
        spotify_responses=acceptance_spotify_responses,
    )
    set_services(svc)
    client = TestClient(app)
    created = client.post("/api/jobs", json={"url": fixture_url})
    assert created.status_code == 201
    job_id = created.json()["id"]
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert len([a for a in detail["albums"] if a["role"] == "bag_pick"]) == 21