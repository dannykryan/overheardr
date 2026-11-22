"""Merge and dedupe tests."""

from app.extraction_types import ExtractedAlbum
from app.merge import merge_albums


def test_merge_adds_takahashi_alternate_and_parallels_mention() -> None:
    description = [
        ExtractedAlbum(
            artist="Yukihiro Takahashi",
            album="Tomorrow's Just Another Day",
            role="bag_pick",
            confidence="high",
            sources=["description"],
        ),
        ExtractedAlbum(
            artist="Fates Warning",
            album="Perfect Symmetry",
            role="bag_pick",
            confidence="high",
            sources=["description"],
        ),
    ]
    llm = [
        ExtractedAlbum(
            artist="Yukihiro Takahashi",
            album="Tomorrow's Just Another Day",
            alternate_titles=["薔薇色の明日"],
            role="bag_pick",
            confidence="medium",
            sources=["transcript_llm"],
        ),
        ExtractedAlbum(
            artist="Fates Warning",
            album="Parallels",
            role="mention",
            confidence="medium",
            sources=["transcript_llm"],
        ),
    ]
    merged = merge_albums(description, llm)
    bag_picks = [m for m in merged if m.role == "bag_pick"]
    assert len(bag_picks) == 2
    tak = next(m for m in merged if m.artist == "Yukihiro Takahashi")
    assert "薔薇色の明日" in tak.alternate_titles
    parallels = next(m for m in merged if m.album == "Parallels")
    assert parallels.role == "mention"


def test_transcript_only_llm_bag_picks() -> None:
    llm = [
        ExtractedAlbum(
            artist="Fates Warning",
            album="Perfect Symmetry",
            role="bag_pick",
            confidence="medium",
            sources=["transcript_llm"],
        )
    ]
    merged = merge_albums([], llm)
    assert len(merged) == 1
    assert merged[0].sources == ["transcript_llm"]