"""API and pipeline integration tests (offline)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from rapidfuzz import fuzz

from app.extraction_types import ExtractedAlbum
from app.main import app
from app.models import JobModel, SessionLocal
from app.pipeline import run_pipeline
from app.services import PipelineServices, set_services

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "TtDMUz6TBIc"


def _run_fixture_pipeline(
    acceptance_spotify_responses: dict,
    *,
    ollama_fn=None,
    ollama_raises=False,
    ollama_invalid_json=False,
    empty_description: bool = False,
) -> str:
    desc = "" if empty_description else None
    svc = PipelineServices(
        fixture_dir=FIXTURE_DIR,
        skip_transcribe=True,
        fixture_description=desc,
        spotify_responses=acceptance_spotify_responses,
        ollama_fn=ollama_fn,
        ollama_raises=ollama_raises,
        ollama_invalid_json=ollama_invalid_json,
    )
    set_services(svc)
    url = "https://www.youtube.com/watch?v=TtDMUz6TBIc"
    with SessionLocal() as session:
        job = JobModel(url=url, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id
    run_pipeline(job_id, svc)
    return job_id


def test_ollama_down_job_still_ready(
    acceptance_spotify_responses: dict,
) -> None:
    job_id = _run_fixture_pipeline(acceptance_spotify_responses, ollama_raises=True)
    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert any("Ollama" in w for w in detail["warnings"])
    assert len([a for a in detail["albums"] if a["role"] == "bag_pick"]) == 21


def test_transcript_only_mocked_llm(acceptance_spotify_responses: dict) -> None:
    picks_json = json.loads((FIXTURE_DIR / "expected_albums.json").read_text())["bag_picks"]

    def ollama_fn(title, desc_albums, transcript):
        return [
            ExtractedAlbum(
                artist=p["artist"],
                album=p["album"],
                year=p.get("year"),
                role="bag_pick",
                confidence="medium",
                sources=["transcript_llm"],
            )
            for p in picks_json
        ]

    job_id = _run_fixture_pipeline(
        acceptance_spotify_responses,
        empty_description=True,
        ollama_fn=ollama_fn,
    )
    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert len(detail["albums"]) >= 21


def test_patch_cannot_select_off_spotify(acceptance_spotify_responses: dict) -> None:
    job_id = _run_fixture_pipeline(acceptance_spotify_responses)
    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    karma = next(a for a in detail["albums"] if a["artist"] == "Karma Moffett")
    assert karma["on_spotify"] is False
    resp = client.patch(
        f"/api/jobs/{job_id}/albums/{karma['id']}",
        json={"selected": True},
    )
    assert resp.status_code == 400


def test_mention_not_auto_selected(acceptance_spotify_responses: dict) -> None:
    def ollama_fn(title, desc_albums, transcript):
        return desc_albums + [
            ExtractedAlbum(
                artist="Fates Warning",
                album="Parallels",
                role="mention",
                confidence="medium",
                sources=["transcript_llm"],
            )
        ]

    job_id = _run_fixture_pipeline(acceptance_spotify_responses, ollama_fn=ollama_fn)
    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    par = next((a for a in detail["albums"] if a["album"] == "Parallels"), None)
    if par:
        assert par["selected"] is False


def test_acceptance_expected_bag_picks(acceptance_spotify_responses: dict) -> None:
    job_id = _run_fixture_pipeline(acceptance_spotify_responses)
    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    expected = json.loads((FIXTURE_DIR / "expected_albums.json").read_text(encoding="utf-8"))

    bag_rows = [a for a in detail["albums"] if a["role"] == "bag_pick"]
    assert len(bag_rows) == 21

    for exp in expected["bag_picks"]:
        match = None
        for row in bag_rows:
            ar = fuzz.token_set_ratio(row["artist"].lower(), exp["artist"].lower())
            al = fuzz.token_set_ratio(row["album"].lower(), exp["album"].lower())
            if ar >= 85 and al >= 85:
                match = row
                break
        assert match is not None, f"Missing bag pick {exp['artist']} - {exp['album']}"

    karma = next(a for a in bag_rows if "Karma" in a["artist"])
    assert karma["on_spotify"] is False

    for exp in expected.get("mentioned_only", []):
        row = next((a for a in detail["albums"] if a["album"] == exp["album"]), None)
        if row:
            assert row["selected"] is False