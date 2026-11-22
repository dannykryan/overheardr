"""Caption download and pipeline integration (offline)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.ingest import TranscriptResult, VideoMetadata, _vtt_to_text
from app.main import app
from app.models import JobModel, SessionLocal
from app.pipeline import run_pipeline
from app.services import PipelineServices, set_services

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "TtDMUz6TBIc"

SAMPLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Fates Warning — Perfect Symmetry

00:00:05.000 --> 00:00:08.000
Morbid Angel Formulas Fatal to the Flesh
"""


def test_vtt_normalization_strips_timestamps() -> None:
    text = _vtt_to_text(SAMPLE_VTT)
    assert "00:00:01" not in text
    assert "WEBVTT" not in text
    assert "Fates Warning" in text
    assert "Morbid Angel" in text


def test_pipeline_uses_caption_text_not_whisper(
    acceptance_spotify_responses: dict,
) -> None:
    caption_text = _vtt_to_text(SAMPLE_VTT)

    def metadata_fn(_url: str, video_id: str) -> VideoMetadata:
        description = (FIXTURE_DIR / "description.txt").read_text(encoding="utf-8")
        return VideoMetadata(
            video_id=video_id,
            title="Caption test video",
            channel="Test",
            duration_seconds=120,
            upload_date="20220101",
            description=description,
            thumbnail_url=None,
            has_captions=True,
            info={"subtitles": {"en": [{}]}, "language": "en"},
        )

    def caption_fn(_vid: str, _url: str, _info: dict) -> TranscriptResult:
        return TranscriptResult(source="captions", text=caption_text, language="en")

    svc = PipelineServices(
        metadata_fn=metadata_fn,
        caption_fn=caption_fn,
        spotify_responses=acceptance_spotify_responses,
    )
    set_services(svc)

    url = "https://www.youtube.com/watch?v=CaptionTst0"
    with SessionLocal() as session:
        job = JobModel(url=url, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    run_pipeline(job_id, svc)

    client = TestClient(app)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "ready"
    assert detail["transcript"]["source"] == "captions"
    assert detail["transcript"]["text"].strip()
    assert "Fates Warning" in detail["transcript"]["text"]