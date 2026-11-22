"""Pytest fixtures — offline DATA_DIR and fixture paths."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.config import settings
from app.models import SessionLocal, init_db
from app.services import PipelineServices, reset_services, set_services


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VIDEO_ID = "TtDMUz6TBIc"
FIXTURE_DIR = REPO_ROOT / "fixtures" / FIXTURE_VIDEO_ID


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setattr(settings, "data_dir", data)
    from app import models

    models._engine.dispose()
    models._engine = create_engine(
        f"sqlite:///{data / 'overheardr.db'}",
        connect_args={"check_same_thread": False},
    )
    models.SessionLocal.configure(bind=models._engine)
    init_db()
    reset_services()
    yield data
    reset_services()


@pytest.fixture
def fixture_services() -> PipelineServices:
    svc = PipelineServices(fixture_dir=FIXTURE_DIR, skip_transcribe=True)
    set_services(svc)
    return svc


def spotify_hit(
    album_id: str,
    name: str,
    artists: list[str],
    *,
    year: str = "1980",
) -> dict:
    return {
        "id": album_id,
        "name": name,
        "artists": artists,
        "release_date": year,
        "album_type": "album",
        "images": [{"url": f"https://example.com/{album_id}.jpg"}],
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
    }


@pytest.fixture
def acceptance_spotify_responses() -> dict:
    """Canned Spotify payloads for the fixture video (Karma returns no hit)."""
    entries = [
        ("Fates Warning", "Perfect Symmetry", "Perfect Symmetry", "1989", "fw1"),
        ("Morbid Angel", "Formulas Fatal To The Flesh", "Formulas Fatal to the Flesh", "1998", "ma1"),
        ("Wallenstein", "Mother Universe", "Mother Universe", "1972", "wa1"),
        ("The Dave Brubeck Quartet", "Time Out", "Time Out", "1959", "db1"),
        ("Osamu Kitajima", "Behind The Light", "Behind The Light", "1991", "ok1"),
        (
            "Carlos Santana & John McLaughlin",
            "Love Devotion Surrender",
            "Love Devotion Surrender",
            "1973",
            "cs1",
        ),
        ("Bernard Xolotl", "Music By Xolotl", "Music By Xolotl", "1978", "bx1"),
        ("Steve Hillage", "Rainbow Dome Musick", "Rainbow Dome Musick", "1979", "sh1"),
        (
            "Abigor",
            "Leytmotif Luzifer",
            "Leytmotif Luzifer (The 7 Temptations of Man)",
            "2014",
            "0D0xCqUDfhkLk4sKTOEiou",
        ),
        ("Tears For Fears", "The Seeds Of Love", "The Seeds of Love", "1989", "tf1"),
        ("Pauline Anna Strom", "Angel Tears In Sunlight", "Angel Tears In Sunlight", "2021", "pas1"),
        (
            "Yukihiro Takahashi",
            "Tomorrow's Just Another Day",
            "薔薇色の明日",
            "2022",
            "yt1",
        ),
        ("XTC", "English Settlement", "English Settlement", "1982", "xtc1"),
        (
            "Seatbelts",
            "Cowboy Bebop (Original Soundtrack)",
            "COWBOY BEBOP ORIGINAL SOUNDTRACK",
            "1998",
            "sb1",
        ),
        ("Eurythmics", "In The Garden", "In The Garden", "1981", "eu1"),
        ("Gong", "Angel's Egg: Radio Gnome Invisible Part II", "Angel's Egg", "1973", "go1"),
        ("Michael Stearns", "Planetary Unfolding", "Planetary Unfolding", "1981", "ms1"),
        ("Klaus Schulze", "Deus Arrakis", "Deus Arrakis", "2022", "ks1"),
        ("Eloy", "Metromania", "Metromania", "1984", "el1"),
        ("Candlemass", "Epicus Doomicus Metallicus", "Epicus Doomicus Metallicus", "1986", "cm1"),
    ]
    out: dict = {}
    for artist, album, spotify_name, year, album_id in entries:
        artists_field = (
            ["Yoko Kanno", "SEAT BELTS"]
            if artist == "Seatbelts"
            else [artist]
        )
        out[f"{artist}::{album}"] = [
            spotify_hit(album_id, spotify_name, artists_field, year=year)
        ]
    out["Karma Moffett::Sitting Still Within Sitting Still Without"] = []
    return out


@pytest.fixture
def fixture_url() -> str:
    return f"https://www.youtube.com/watch?v={FIXTURE_VIDEO_ID}"