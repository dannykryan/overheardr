"""Offline Spotify matcher tests with canned search payloads."""

from app.extraction_types import ExtractedAlbum
from app.spotify import match_with_canned_responses
from tests.conftest import spotify_hit


def test_takahashi_japanese_title() -> None:
    album = ExtractedAlbum(
        artist="Yukihiro Takahashi",
        album="Tomorrow's Just Another Day",
        alternate_titles=["薔薇色の明日"],
        year=1983,
        role="bag_pick",
        sources=["description"],
    )
    responses = {
        "薔薇色の明日": [
            spotify_hit("yt1", "薔薇色の明日", [album.artist], year="2022")
        ],
        "tomorrow": [],
    }
    m = match_with_canned_responses(album, responses)
    assert m.on_spotify
    assert m.spotify_album_name == "薔薇色の明日"


def test_karma_no_hit() -> None:
    album = ExtractedAlbum(
        artist="Karma Moffett",
        album="Sitting Still Within / Sitting Still Without",
        role="bag_pick",
        sources=["description"],
    )
    m = match_with_canned_responses(album, {"*": []})
    assert not m.on_spotify


def test_seatbelts_aliases() -> None:
    album = ExtractedAlbum(
        artist="Seatbelts",
        album="Cowboy Bebop (Original Soundtrack)",
        alternate_titles=["Cowboy Bebop [OST]"],
        year=1998,
        role="bag_pick",
        sources=["description"],
    )
    responses = {
        f"{album.artist}::{album.album}": [
            spotify_hit(
                "sb1",
                "COWBOY BEBOP ORIGINAL SOUNDTRACK",
                ["Yoko Kanno", "SEAT BELTS"],
                year="1998",
            )
        ]
    }
    m = match_with_canned_responses(album, responses)
    assert m.on_spotify


def test_hillage_musick() -> None:
    album = ExtractedAlbum(
        artist="Steve Hillage",
        album="Rainbow Dome Musick",
        year=1979,
        role="bag_pick",
        sources=["description"],
    )
    responses = {
        f"{album.artist}::{album.album}": [
            spotify_hit("sh1", "Rainbow Dome Musick", [album.artist], year="1979")
        ]
    }
    m = match_with_canned_responses(album, responses)
    assert m.on_spotify


def test_abigor_long_title() -> None:
    album = ExtractedAlbum(
        artist="Abigor",
        album="Leytmotif Luzifer",
        year=2014,
        role="bag_pick",
        sources=["description"],
    )
    responses = {
        f"{album.artist}::{album.album}": [
            spotify_hit(
                "0D0xCqUDfhkLk4sKTOEiou",
                "Leytmotif Luzifer (The 7 Temptations of Man)",
                [album.artist],
                year="2014",
            )
        ]
    }
    m = match_with_canned_responses(album, responses)
    assert m.on_spotify
    assert m.spotify_album_id == "0D0xCqUDfhkLk4sKTOEiou"


def test_remaster_year_accepted() -> None:
    album = ExtractedAlbum(
        artist="Wallenstein",
        album="Mother Universe",
        year=1972,
        role="bag_pick",
        sources=["description"],
    )
    responses = {
        f"{album.artist}::{album.album}": [
            spotify_hit("wa1", "Mother Universe", [album.artist], year="2020")
        ]
    }
    m = match_with_canned_responses(album, responses)
    assert m.on_spotify