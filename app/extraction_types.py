"""Shared types for album extraction (parser, LLM, merge)."""

from dataclasses import dataclass, field
from typing import Literal

Confidence = Literal["high", "medium", "low"]
Role = Literal["bag_pick", "mention"]
Source = Literal["description", "transcript_llm"]


@dataclass
class ExtractedAlbum:
    artist: str
    album: str
    year: int | None = None
    alternate_titles: list[str] = field(default_factory=list)
    role: Role = "bag_pick"
    confidence: Confidence = "high"
    sources: list[Source] = field(default_factory=list)
    evidence: str | None = None
    speaker: str | None = None