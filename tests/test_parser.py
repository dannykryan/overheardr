"""Description parser tests."""

from pathlib import Path

from app.parser import parse_description

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "TtDMUz6TBIc"


def test_description_parser_yields_21_bag_picks_in_order() -> None:
    description = (FIXTURE_DIR / "description.txt").read_text(encoding="utf-8")
    picks = parse_description(description)
    assert len(picks) == 21
    assert all(p.role == "bag_pick" for p in picks)
    assert all(p.sources == ["description"] for p in picks)

    artists = [p.artist for p in picks]
    assert artists[0] == "Fates Warning"
    assert artists[-1] == "Candlemass"
    assert picks[11].artist == "Yukihiro Takahashi"
    assert picks[12].artist == "XTC"
    assert picks[12].album == "English Settlement"
    assert picks[13].artist == "Seatbelts"
    assert "Cowboy Bebop" in picks[13].album
    assert picks[14].artist == "Karma Moffett"
    assert len({(p.artist, p.album) for p in picks}) == 21