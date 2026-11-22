"""String normalization for fuzzy album/artist matching."""

import re
import unicodedata

_PAREN_RE = re.compile(
    r"\s*\((?:remaster|deluxe|expanded|anniversary|edition|reissue|bonus)[^)]*\)",
    re.IGNORECASE,
)
_FEAT_RE = re.compile(r"\b(?:feat\.?|ft\.?|featuring)\s+[^()]+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize(text: str, *, strip_parens_for_query: bool = True) -> str:
    """NFKC lowercase, unify &/and/+, strip feat, punctuation, leading 'the'."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    if strip_parens_for_query:
        t = _PAREN_RE.sub("", t)
    t = _FEAT_RE.sub("", t)
    t = t.replace("&", " and ").replace("+", " and ")
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    if t.startswith("the "):
        t = t[4:]
    return t


def pair_key(artist: str, album: str) -> str:
    return f"{normalize(artist)}|{normalize(album)}"