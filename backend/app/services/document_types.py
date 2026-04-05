from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedSegment:
    text: str
    page_start: int | None
    page_end: int | None
    source_type: str


@dataclass(slots=True)
class ParsedDocument:
    segments: list[ParsedSegment] = field(default_factory=list)


@dataclass(slots=True)
class VectorChunk:
    small_chunk_text: str
    large_chunk_text: str
    small_chunk_index: int
    large_chunk_id: str
    page_start: int | None
    page_end: int | None
    source_type: str


@dataclass(slots=True)
class VectorizationResult:
    chunk_count: int
    text_chunk_count: int = 0
    image_chunk_count: int = 0
