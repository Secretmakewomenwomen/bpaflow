from app.services.chunking_service import ChunkingService
from app.services.document_types import ParsedSegment


def test_chunking_service_builds_small_chunks_and_large_chunk_links() -> None:
    service = ChunkingService(
        small_chunk_size=80,
        small_chunk_overlap=20,
        large_chunk_size=160,
    )
    text = ("甲" * 90) + ("乙" * 90)

    chunks = service.build_chunks(
        [
            ParsedSegment(
                text=text,
                page_start=1,
                page_end=1,
                source_type="pdf_text",
            )
        ]
    )

    assert len(chunks) == 3
    assert chunks[0].small_chunk_index == 0
    assert chunks[1].small_chunk_index == 1
    assert chunks[0].large_chunk_id == chunks[1].large_chunk_id
    assert chunks[2].large_chunk_id != chunks[0].large_chunk_id
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1
    assert len(chunks[0].large_chunk_text) == 160


def test_chunking_service_returns_empty_for_empty_segments() -> None:
    service = ChunkingService()

    chunks = service.build_chunks([])

    assert chunks == []
