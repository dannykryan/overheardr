"""Merge description and LLM extraction results (SPEC §6.3)."""

from rapidfuzz import fuzz

from app.extraction_types import ExtractedAlbum, Source
from app.normalize import normalize, pair_key

_MATCH_THRESHOLD = 82


def _albums_match(a: ExtractedAlbum, b: ExtractedAlbum) -> bool:
    if pair_key(a.artist, a.album) == pair_key(b.artist, b.album):
        return True
    for alt in a.alternate_titles + [a.album]:
        for altb in b.alternate_titles + [b.album]:
            if normalize(alt) == normalize(altb):
                ar = fuzz.token_set_ratio(normalize(a.artist), normalize(b.artist))
                if ar >= 70:
                    return True
    ar = fuzz.token_set_ratio(normalize(a.artist), normalize(b.artist))
    al = fuzz.token_set_ratio(normalize(a.album), normalize(b.album))
    return ar >= 75 and al >= _MATCH_THRESHOLD


def _merge_pair(desc: ExtractedAlbum | None, llm: ExtractedAlbum | None) -> ExtractedAlbum:
    if desc and llm:
        artist, album = desc.artist, desc.album
        alts = list(dict.fromkeys(desc.alternate_titles + llm.alternate_titles))
        role = "bag_pick" if desc.role == "bag_pick" or llm.role == "bag_pick" else "mention"
        conf_order = {"high": 3, "medium": 2, "low": 1}
        confidence = desc.confidence if conf_order[desc.confidence] >= conf_order[llm.confidence] else llm.confidence
        sources: list[Source] = list(dict.fromkeys(desc.sources + llm.sources))
        year = desc.year if desc.year is not None else llm.year
        return ExtractedAlbum(
            artist=artist,
            album=album,
            year=year,
            alternate_titles=alts,
            role=role,
            confidence=confidence,
            sources=sources,
            evidence=llm.evidence or desc.evidence,
            speaker=llm.speaker or desc.speaker,
        )
    if desc:
        return desc
    assert llm is not None
    return llm


def merge_albums(
    description_albums: list[ExtractedAlbum],
    llm_albums: list[ExtractedAlbum],
) -> list[ExtractedAlbum]:
    """Description wins spelling; union alternates; bag_pick if either source says so."""
    merged: list[ExtractedAlbum] = []
    used_llm: set[int] = set()

    for desc in description_albums:
        match_idx = None
        for i, llm in enumerate(llm_albums):
            if i in used_llm:
                continue
            if _albums_match(desc, llm):
                match_idx = i
                break
        if match_idx is not None:
            used_llm.add(match_idx)
            merged.append(_merge_pair(desc, llm_albums[match_idx]))
        else:
            merged.append(desc)

    for i, llm in enumerate(llm_albums):
        if i in used_llm:
            continue
        if llm.role == "mention" and _is_non_album_mention(llm):
            continue
        merged.append(llm)

    return merged


def _is_non_album_mention(album: ExtractedAlbum) -> bool:
    """Drop TV-series style mentions that are not albums."""
    combined = f"{album.artist} {album.album}".lower()
    if "tv series" in combined or "anime series" in combined:
        return True
    return False